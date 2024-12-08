import grpc
import threading
import time
from enum import Enum
from dataclasses import dataclass
from concurrent import futures
import random
import logging

import raft_pb2
import raft_pb2_grpc

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] Node-%(node_id)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("raft.log"), logging.StreamHandler()]
)

class State(Enum):
    FOLLOWER = "Follower"
    CANDIDATE = "Candidate"
    LEADER = "Leader"

@dataclass
class LogEntry:
    term: int
    command: str

class Node(raft_pb2_grpc.RaftServicer):
    def __init__(self, node_id, peers):
        self.node_id = node_id
        self.peers = peers
        self.connected_nodes = set(peers)
        self.current_state = State.FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.log = []
        self.commit_index = 0
        self.last_applied = 0
        self.snapshot = None  # Snapshot to store compressed state
        self.leader_id = None
        self.lock = threading.Lock()
        self.election_timeout = time.time() + self.random_timeout()
        self.logger = logging.LoggerAdapter(logging.getLogger(__name__), {"node_id": self.node_id})

    def random_timeout(self):
        return 5 + random.uniform(0, 5)

    def RequestVote(self, request, context):
        with self.lock:
            if request.candidate_id not in self.connected_nodes:
                self.logger.warning("Ignoring RequestVote from disconnected Node-%d", request.candidate_id)
                return raft_pb2.VoteResponse(term=self.current_term, vote_granted=False)

            if request.term > self.current_term:
                self.current_term = request.term
                self.voted_for = None

            vote_granted = False
            if (self.voted_for in (None, request.candidate_id) and
                (len(self.log) == 0 or
                 (request.last_log_term > self.log[-1].term or
                  (request.last_log_term == self.log[-1].term and
                   request.last_log_index >= len(self.log))))):
                vote_granted = True
                self.voted_for = request.candidate_id
                self.election_timeout = time.time() + self.random_timeout()

            return raft_pb2.VoteResponse(term=self.current_term, vote_granted=vote_granted)

    def AppendEntries(self, request, context):
        with self.lock:
            if request.leader_id not in self.connected_nodes:
                self.logger.warning("Ignoring AppendEntries from disconnected Node-%d", request.leader_id)
                return raft_pb2.AppendEntriesResponse(term=self.current_term, success=False)

            if request.term < self.current_term:
                return raft_pb2.AppendEntriesResponse(term=self.current_term, success=False)

            if len(self.log) <= request.prev_log_index or self.log[request.prev_log_index].term != request.prev_log_term:
                return raft_pb2.AppendEntriesResponse(term=self.current_term, success=False)

            self.log = self.log[:request.prev_log_index + 1] + request.entries
            self.commit_index = min(request.leader_commit, len(self.log))
            self.election_timeout = time.time() + self.random_timeout()
            return raft_pb2.AppendEntriesResponse(term=self.current_term, success=True)

    def InstallSnapshot(self, request, context):
        with self.lock:
            if request.term >= self.current_term:
                self.snapshot = request.snapshot_data
                self.log = []  # Reset log after applying snapshot
                self.current_term = request.term
                self.commit_index = request.last_included_index
                self.logger.info("Installed snapshot from leader.")
            return raft_pb2.InstallSnapshotResponse(term=self.current_term)

    def FragmentNetwork(self, request, context):
        with self.lock:
            disconnected_nodes = set(request.disconnected_nodes)
            self.connected_nodes = set(self.peers) - disconnected_nodes
            self.logger.info("Fragmented network. Connected nodes: %s", self.connected_nodes)
            return raft_pb2.NetworkFragmentationResponse(success=True)

    def start_server(self):
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        raft_pb2_grpc.add_RaftServicer_to_server(self, server)
        server.add_insecure_port(f'[::]:500{self.node_id}')
        server.start()
        self.logger.info("Server started as %s", self.current_state.value)
        return server

    def start_election(self):
        with self.lock:
            self.current_state = State.CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.election_timeout = time.time() + self.random_timeout()
            self.logger.info("Starting election for term %d", self.current_term)

        votes = 1
        for peer in self.connected_nodes:
            try:
                channel = grpc.insecure_channel(f'[::]:500{peer}')
                stub = raft_pb2_grpc.RaftStub(channel)
                response = stub.RequestVote(
                    raft_pb2.VoteRequest(
                        term=self.current_term,
                        candidate_id=self.node_id,
                        last_log_index=len(self.log) - 1 if self.log else -1,
                        last_log_term=self.log[-1].term if self.log else -1
                    )
                )
                if response.vote_granted:
                    votes += 1
            except Exception as e:
                self.logger.error("Error contacting Node-%d: %s", peer, str(e))

        if votes > len(self.peers) // 2:
            with self.lock:
                self.current_state = State.LEADER
                self.logger.info("Became the leader for term %d", self.current_term)

    def run(self):
        while True:
            time.sleep(1)
            if self.current_state == State.FOLLOWER and time.time() > self.election_timeout:
                self.logger.warning("Election timeout reached. Starting election.")
                self.start_election()
