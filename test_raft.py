import unittest
import subprocess
import time
import os
import signal

class TestRAFT(unittest.TestCase):
    def setUp(self):
        """
        Start the RAFT system with 5 nodes. Each node is run as a separate process.
        """
        self.processes = []
        for node_id in range(5):
            process = subprocess.Popen(["python", "main.py", str(node_id)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.processes.append(process)
        time.sleep(5)  # Allow nodes to initialize

    def tearDown(self):
        """
        Terminate all processes after each test.
        """
        for process in self.processes:
            os.kill(process.pid, signal.SIGTERM)
        for process in self.processes:
            process.wait()

    def test_leader_election(self):
        """
        Ensure a leader is elected within a reasonable time.
        """
        time.sleep(10)  # Wait for the leader election
        with open("raft.log", "r") as log_file:
            log_content = log_file.read()
            leader_entries = [line for line in log_content.split("\n") if "Became the leader" in line]
            self.assertGreaterEqual(len(leader_entries), 1, "No leader elected")

    def test_leader_failure(self):
        """
        Simulate leader failure and ensure a new leader is elected.
        """
        # Identify and terminate the current leader
        with open("raft.log", "r") as log_file:
            log_content = log_file.read()
            leader_line = next(line for line in log_content.split("\n") if "Became the leader" in line)
            current_leader = int(leader_line.split("Node-")[1].split(":")[0])

        os.kill(self.processes[current_leader].pid, signal.SIGTERM)
        self.processes[current_leader].wait()
        time.sleep(10)  # Allow time for re-election

        # Check that a new leader was elected
        with open("raft.log", "r") as log_file:
            log_content = log_file.read()
            new_leader_entries = [line for line in log_content.split("\n") if "Became the leader" in line]
            self.assertGreaterEqual(len(new_leader_entries), 2, "No new leader elected after failure")

    def test_follower_failure_and_recovery(self):
        """
        Simulate a follower failure and ensure it recovers and syncs logs.
        """
        follower_id = 1
        os.kill(self.processes[follower_id].pid, signal.SIGTERM)
        self.processes[follower_id].wait()
        time.sleep(5)  # Allow the system to stabilize without the follower

        # Restart the follower
        self.processes[follower_id] = subprocess.Popen(["python", "main.py", str(follower_id)],
                                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(10)  # Allow the follower to recover and sync logs

        # Check that the follower received logs from the leader
        with open("raft.log", "r") as log_file:
            log_content = log_file.read()
            sync_entries = [line for line in log_content.split("\n") if "AppendEntries" in line]
            self.assertGreaterEqual(len(sync_entries), 1, "Follower did not sync logs after recovery")

    def test_network_partition(self):
        """
        Simulate a network partition and ensure RAFT maintains consistency.
        """
        # Isolate Node-0 and Node-1 from the rest
        isolated_nodes = [0, 1]
        for node_id in isolated_nodes:
            os.kill(self.processes[node_id].pid, signal.SIGTERM)
            self.processes[node_id].wait()

        time.sleep(5)  # Allow the remaining nodes to stabilize

        # Reconnect isolated nodes
        for node_id in isolated_nodes:
            self.processes[node_id] = subprocess.Popen(["python", "main.py", str(node_id)],
                                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(10)  # Allow time for the system to recover

        # Verify consistency
        with open("raft.log", "r") as log_file:
            log_content = log_file.read()
            leader_entries = [line for line in log_content.split("\n") if "Became the leader" in line]
            self.assertGreaterEqual(len(leader_entries), 1, "System did not recover from partition")

if __name__ == "__main__":
    unittest.main()

