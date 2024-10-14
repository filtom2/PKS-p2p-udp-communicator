import socket
import threading

def start_server(local_host='localhost', local_port=65432):
    """
    Starts the server to listen for incoming UDP messages.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_sock:
        try:
            server_sock.bind((local_host, local_port))
            print(f"Server listening on {local_host}:{local_port}")
            client_address = None
            stop_event = threading.Event()

            def receive_messages():
                nonlocal client_address
                while not stop_event.is_set():
                    try:
                        data, addr = server_sock.recvfrom(1024)
                        if not data:
                            continue
                        if client_address is None:
                            client_address = addr
                            print(f"Connected to client at {client_address}")
                        print(f"\n[Client {addr}] {data.decode()}")
                    except Exception as e:
                        print(f"\nReceiving error: {e}")
                        stop_event.set()
                        break

            def send_messages():
                while not stop_event.is_set():
                    try:
                        message = input()
                        if message.lower() == 'exit':
                            print("Exiting communication.")
                            stop_event.set()
                            break
                        if client_address:
                            server_sock.sendto(message.encode(), client_address)
                        else:
                            print("No client connected to send messages.")
                    except Exception as e:
                        print(f"\nSending error: {e}")
                        stop_event.set()
                        break

            # Start receiving and sending threads
            recv_thread = threading.Thread(target=receive_messages, daemon=True)
            send_thread = threading.Thread(target=send_messages, daemon=True)
            recv_thread.start()
            send_thread.start()

            # Wait for both threads to finish
            recv_thread.join()
            send_thread.join()
            print("Server stopped communication.")
        except Exception as e:
            print(f"Server error: {e}")

def start_client(local_host='localhost', local_port=65433, server_host='localhost', server_port=65432):
    """
    Starts the client to send and receive UDP messages to/from the server.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_sock:
        try:
            client_sock.bind((local_host, local_port))
            print(f"Client listening on {local_host}:{local_port}")
            server_address = (server_host, server_port)
            stop_event = threading.Event()

            def receive_messages():
                while not stop_event.is_set():
                    try:
                        data, addr = client_sock.recvfrom(1024)
                        if not data:
                            continue
                        print(f"\n[Server {addr}] {data.decode()}")
                    except Exception as e:
                        print(f"\nReceiving error: {e}")
                        stop_event.set()
                        break

            def send_messages():
                while not stop_event.is_set():
                    try:
                        message = input()
                        if message.lower() == 'exit':
                            print("Exiting communication.")
                            stop_event.set()
                            break
                        client_sock.sendto(message.encode(), server_address)
                    except Exception as e:
                        print(f"\nSending error: {e}")
                        stop_event.set()
                        break

            # Start receiving and sending threads
            recv_thread = threading.Thread(target=receive_messages, daemon=True)
            send_thread = threading.Thread(target=send_messages, daemon=True)
            recv_thread.start()
            send_thread.start()

            # Wait for both threads to finish
            recv_thread.join()
            send_thread.join()
            print("Client stopped communication.")
        except Exception as e:
            print(f"Client error: {e}")

def main():
    """
    Main function to choose between server and client modes with UDP bidirectional communication.
    """
    while True:
        mode = input("\nSelect mode (server/client/exit): ").strip().lower()
        if mode == 'server':
            local_host = input("Enter host to bind (default 'localhost'): ") or 'localhost'
            port_input = input("Enter port to bind (default 65432): ") or '65432'
            try:
                local_port = int(port_input)
                start_server(local_host, local_port)
            except ValueError:
                print("Invalid port number. Please enter an integer.")
        elif mode == 'client':
            local_host = input("Enter your local host to bind (default 'localhost'): ") or 'localhost'
            local_port_input = input("Enter your local port to bind (default 65433): ") or '65433'
            server_host = input("Enter server host to connect (default 'localhost'): ") or 'localhost'
            server_port_input = input("Enter server port to connect (default 65432): ") or '65432'
            try:
                local_port = int(local_port_input)
                server_port = int(server_port_input)
                start_client(local_host, local_port, server_host, server_port)
            except ValueError:
                print("Invalid port number. Please enter integers.")
        elif mode == 'exit':
            print("Exiting program.")
            break
        else:
            print("Invalid mode selected. Please choose 'server', 'client', or 'exit'.")

if __name__ == "__main__":
    main()
