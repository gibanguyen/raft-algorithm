import threading
from node import Node

def main():
    nodes = []
    num_nodes = 5
    peers = [i for i in range(num_nodes)]

    for node_id in range(num_nodes):
        peers_without_self = [p for p in peers if p != node_id]
        node = Node(node_id=node_id, peers=peers_without_self)
        threading.Thread(target=node.run).start()
        nodes.append(node)

    servers = [node.start_server() for node in nodes]
    try:
        for server in servers:
            server.wait_for_termination()
    except KeyboardInterrupt:
        print("Shutting down servers.")


if __name__ == "__main__":
    main()
