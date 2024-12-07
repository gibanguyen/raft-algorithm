import grpc
import threading
import time
from enum import Enum
from dataclasses import dataclass
from concurrent import futures
import random
import logging

# Import generated gRPC code
import raft_pb2
import raft_pb2_grpc

# Configure logging
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
        self.current_state = State.FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.log = []
        self.commit_index = 0
        self.last_applied = 0
        self.leader_id = None
        self.lock = threading.Lock()
        self.election_timeout = time.time() + self.random_timeout()
        self.logger = logging.LoggerAdapter(logging.getLogger(__name__), {"node_id": self.node_id})

    def random_timeout(self):
        # Random timeout between 5 and 10 seconds
        return 5 + random.uniform(0, 5)

    def RequestVote(self, request, context):
        with self.lock:
            if request.term > self.current_term:
                self.current_term = request.term
                self.voted_for = None
                self.logger.info("Updated term to %d due to RequestVote RPC", self.current_term)

            vote_granted = False
            if self.voted_for in (None, request.candidate_id):
                vote_granted = True
                self.voted_for = request.candidate_id
                self.election_timeout = time.time() + self.random_timeout()
                self.logger.info("Voted for Node-%d in term %d", request.candidate_id, self.current_term)

            return raft_pb2.VoteResponse(term=self.current_term, vote_granted=vote_granted)

    def AppendEntries(self, request, context):
        with self.lock:
            success = False
            if request.term >= self.current_term:
                self.current_term = request.term
                self.leader_id = request.leader_id
                self.election_timeout = time.time() + self.random_timeout()
                self.logger.info("Received AppendEntries RPC from leader Node-%d for term %d", request.leader_id, request.term)
                success = True

            return raft_pb2.AppendEntriesResponse(term=self.current_term, success=success)

    def start_server(self):
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        raft_pb2_grpc.add_RaftServicer_to_server(self, server)
        server.add_insecure_port(f'[::]:500{self.node_id}')
        server.start()
        self.logger.info("Server started as %s", self.current_state.value)
        print(f"Node {self.node_id} started as {self.current_state.value}")
        return server

    def start_election(self):
        with self.lock:
            self.current_state = State.CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.election_timeout = time.time() + self.random_timeout()
            self.logger.info("Starting election for term %d", self.current_term)

        votes = 1  # Self-vote
        for peer in self.peers:
            try:
                channel = grpc.insecure_channel(f'[::]:500{peer}')
                stub = raft_pb2_grpc.RaftStub(channel)
                response = stub.RequestVote(
                    raft_pb2.VoteRequest(term=self.current_term, candidate_id=self.node_id)
                )
                if response.vote_granted:
                    votes += 1
                    self.logger.info("Received vote from Node-%d for term %d", peer, self.current_term)
            except Exception as e:
                self.logger.error("Error contacting Node-%d: %s", peer, str(e))
                continue

        if votes > len(self.peers) // 2:
            with self.lock:
                self.current_state = State.LEADER
                self.logger.info("Became the leader for term %d", self.current_term)


    def run(self):
        while True:
            time.sleep(1)
            if self.current_state == State.FOLLOWER and time.time() > self.election_timeout:
                self.logger.warning("Election timeout reached. Starting election.")
                print(f"Node {self.node_id} starting election.")
                self.start_election()

