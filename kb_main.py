import socket
import threading

# +---------+------------+-------------+--------+--------+-------+
# | TYPE    | Frag. Nr   | Total Frags |  CRC   | Flags  | Data  |
# +---------+------------+-------------+--------+--------+-------+
# | 1 Byte  |  2 Byte    |   2 Byte    |  4 Byte| 1 Byte | var   |
# +---------+------------+-------------+--------+--------+-------+


MSG_DEFAULT = 0
MSG_SYN = 1
MSG_SYN_ACK = 2
MSG_ACK = 3
MSG_FIN = 4


def create_message(msg_type, data=b''):
    return bytes([msg_type]) + data

def parse_message(message):
    msg_type = message[0]
    data = message[1:]
    return msg_type, data

# Server hs
def handle_handshake_server(server_sock):
    """
    Handle the handshake process for the server.
    Server receives 1.5) SYN and sends 2) SYN_ACK then receives 3.5) ACK from client
    """
    data, addr = server_sock.recvfrom(1024)
    msg_type, _ = parse_message(data)
    if msg_type == MSG_SYN:
        server_sock.sendto(create_message(MSG_SYN_ACK), addr)
        data, addr = server_sock.recvfrom(1024)
        msg_type, _ = parse_message(data)
        if msg_type == MSG_ACK:
            print(f"Handshake complete with client at {addr}")
            return addr
    return None

# Client hs
def handle_handshake_client(client_sock, server_address):
    """
    Sends 1) SYN to server,  receives 2.5) SYN_ACK, send 3) ACK to server
    """
    client_sock.sendto(create_message(MSG_SYN), server_address)
    data, addr = client_sock.recvfrom(1024)
    msg_type, _ = parse_message(data)
    if msg_type == MSG_SYN_ACK:
        client_sock.sendto(create_message(MSG_ACK), server_address)
        print("Handshake complete with server")
        return True
    return False

# Server Code
def start_server(local_host='localhost', local_port=65432):
    """
    Server code to start listening on the specified host and port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_sock:
        try:
            server_sock.bind((local_host, local_port))
            print(f"Server listening on {local_host}:{local_port}")
            client_address = None
            stop_event = threading.Event()

            client_address = handle_handshake_server(server_sock)
            if client_address:
                pass
            else:
                print("Handshake failed.")
                return

            def receive_messages():
                while not stop_event.is_set():
                    try:
                        data, addr = server_sock.recvfrom(1024)
                        if not data:
                            continue
                        msg_type, msg_data = parse_message(data)
                        if msg_type == MSG_FIN:
                            print("Client initiated termination.")
                            stop_event.set()
                            break
                        elif msg_type == MSG_DEFAULT:
                            print(f"\n[Client {addr}] {msg_data.decode()}")
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
                            server_sock.sendto(create_message(MSG_FIN), client_address)
                            stop_event.set()
                            break
                        if client_address:
                            server_sock.sendto(create_message(MSG_DEFAULT, message.encode()), client_address)
                        else:
                            print("No client connected to send messages.")
                    except Exception as e:
                        print(f"\nSending error: {e}")
                        stop_event.set()
                        break

            recv_thread = threading.Thread(target=receive_messages, daemon=True)
            send_thread = threading.Thread(target=send_messages, daemon=True)
            recv_thread.start()
            send_thread.start()
            recv_thread.join()
            send_thread.join()
            print("Server stopped communication.")
        except Exception as e:
            print(f"Server error: {e}")

# Client Code
def start_client(local_host='localhost', local_port=65433, server_host='localhost', server_port=65432):
    """
    Client code to start listening on the specified host and port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_sock:
        try:
            client_sock.bind((local_host, local_port))
            print(f"Client listening on {local_host}:{local_port}")
            server_address = (server_host, server_port)
            stop_event = threading.Event()

            if handle_handshake_client(client_sock, server_address):
                pass
            else:
                print("Handshake failed.")
                return

            def receive_messages():
                while not stop_event.is_set():
                    try:
                        data, addr = client_sock.recvfrom(1024)
                        if not data:
                            continue
                        msg_type, msg_data = parse_message(data)
                        if msg_type == MSG_FIN:
                            print("Server initiated termination.")
                            stop_event.set()
                            break
                        elif msg_type == MSG_DEFAULT:
                            print(f"\n[Server {addr}] {msg_data.decode()}")
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
                            client_sock.sendto(create_message(MSG_FIN), server_address)
                            stop_event.set()
                            break
                        client_sock.sendto(create_message(MSG_DEFAULT, message.encode()), server_address)
                    except Exception as e:
                        print(f"\nSending error: {e}")
                        stop_event.set()
                        break

            recv_thread = threading.Thread(target=receive_messages, daemon=True)
            send_thread = threading.Thread(target=send_messages, daemon=True)
            recv_thread.start()
            send_thread.start()
            recv_thread.join()
            send_thread.join()
            print("Client stopped communication.")
        except Exception as e:
            print(f"Client error: {e}")

# Main Function
def main():
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
