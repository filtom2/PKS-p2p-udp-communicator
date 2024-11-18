import socket
import threading
import zlib
import time

# Message Types
MSG_DEFAULT = 0
MSG_SYN = 1
MSG_SYN_ACK = 2
MSG_ACK = 3
MSG_FIN = 4
MSG_KEEP_ALIVE = 5


def create_message(msg_type, sequence_number, data=b''):
    crc = zlib.crc32(data)
    crc_bytes = crc.to_bytes(4, 'big')
    sequence_bytes = sequence_number.to_bytes(2, 'big')
    return bytes([msg_type]) + sequence_bytes + crc_bytes + data

def parse_message(message):
    msg_type = message[0]
    sequence_number = int.from_bytes(message[1:3], 'big')
    received_crc = int.from_bytes(message[3:7], 'big')
    data = message[7:]
    if zlib.crc32(data) != received_crc:
        print("Warning: CRC mismatch!")
        return None, None
    return msg_type, data


def keep_alive(sock, addr, stop_event, lost_connection_event, interval=5):
    while not stop_event.is_set():
        time.sleep(interval)
        sock.sendto(create_message(MSG_KEEP_ALIVE, 0), addr)
        
        if lost_connection_event.is_set():
            stop_event.set()
            break

# Function to handle receiving messages and connection re-establishment
def receive_messages(sock, stop_event, lost_connection_event, addr, interval=5, buffer_size=1024):
    last_activity = time.time()

    while not stop_event.is_set():
        try:
            sock.settimeout(interval)
            data, _ = sock.recvfrom(buffer_size)
            if data:
                msg_type, msg_data = parse_message(data)
                if msg_type == MSG_FIN:
                    print("Peer has closed the connection.")
                    stop_event.set()
                    break
                elif msg_type == MSG_KEEP_ALIVE:
                    last_activity = time.time()  # Reset activity timer on Keep-Alive
                elif msg_type == MSG_DEFAULT:
                    print(f"[Peer {addr}] {msg_data.decode()}")
                    last_activity = time.time()
            else:
                raise Exception("No data received")

            # Check if the connection is inactive
            if time.time() - last_activity > interval * 3:
                print("Connection lost. No Keep-Alive received after 3 intervals.")
                lost_connection_event.set()
                stop_event.set()
                break

        except socket.timeout:
            # Handle timeout in the main loop without disrupting `keep_alive`
            if time.time() - last_activity > interval * 3: # 3 times checks
                print("Connection lost due to inactivity.")
                lost_connection_event.set()
                stop_event.set()
                break
        except Exception as e:
            print(f"Receiving error: {e}")
            stop_event.set()
            break

# Server and client handshake functions
def handle_handshake_server(server_sock):
    data, addr = server_sock.recvfrom(1024)
    msg_type, _ = parse_message(data)
    if msg_type == MSG_SYN:
        server_sock.sendto(create_message(MSG_SYN_ACK, 0), addr)
        data, addr = server_sock.recvfrom(1024)
        msg_type, _ = parse_message(data)
        if msg_type == MSG_ACK:
            print(f"\nHandshake complete with client at {addr}\n")
            return addr
    return None

def handle_handshake_client(client_sock, server_address):
    client_sock.sendto(create_message(MSG_SYN, 0), server_address)
    data, _ = client_sock.recvfrom(1024)
    msg_type, _ = parse_message(data)
    if msg_type == MSG_SYN_ACK:
        client_sock.sendto(create_message(MSG_ACK, 0), server_address)
        print("\nHandshake complete with server.\n")
        return True
    return False


def start_server(local_host='localhost', local_port=65432):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_sock:
        try:
            server_sock.bind((local_host, local_port))
            print(f"Server listening on {local_host}:{local_port}")
            stop_event = threading.Event()
            lost_connection_event = threading.Event()

            client_address = handle_handshake_server(server_sock)
            if client_address:
                keep_alive_thread = threading.Thread(
                    target=keep_alive,
                    args=(server_sock, client_address, stop_event, lost_connection_event),
                    daemon=True
                )
                keep_alive_thread.start()

                recv_thread = threading.Thread(
                    target=receive_messages,
                    args=(server_sock, stop_event, lost_connection_event, client_address),
                    daemon=True
                )
                recv_thread.start()

                send_thread = threading.Thread(
                    target=send_messages,
                    args=(server_sock, client_address, stop_event),
                    daemon=True
                )
                send_thread.start()

                recv_thread.join()
                send_thread.join()
                keep_alive_thread.join()
                print("Server stopped communication.")
            else:
                print("Handshake failed.")
        except Exception as e:
            print(f"Server error: {e}")


def start_client(local_host='localhost', local_port=65433, server_host='localhost', server_port=65432):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_sock:
        try:
            client_sock.bind((local_host, local_port))
            print(f"Client listening on {local_host}:{local_port}")
            server_address = (server_host, server_port)
            stop_event = threading.Event()
            lost_connection_event = threading.Event()

            if handle_handshake_client(client_sock, server_address):
                keep_alive_thread = threading.Thread(
                    target=keep_alive,
                    args=(client_sock, server_address, stop_event, lost_connection_event),
                    daemon=True
                )
                keep_alive_thread.start()

                recv_thread = threading.Thread(
                    target=receive_messages,
                    args=(client_sock, stop_event, lost_connection_event, server_address),
                    daemon=True
                )
                recv_thread.start()

                send_thread = threading.Thread(
                    target=send_messages,
                    args=(client_sock, server_address, stop_event),
                    daemon=True
                )
                send_thread.start()

                recv_thread.join()
                send_thread.join()
                keep_alive_thread.join()
                print("Client stopped communication.")
            else:
                print("Handshake failed.")
        except Exception as e:
            print(f"Client error: {e}")


def send_messages(sock, addr, stop_event):
    while not stop_event.is_set():
        try:
            message = input()
            if message.lower() == 'exit':
                sock.sendto(create_message(MSG_FIN, 0), addr)
                stop_event.set()
                break
            sock.sendto(create_message(MSG_DEFAULT, 0, message.encode()), addr)
        except Exception as e:
            print(f"Sending error: {e}")
            stop_event.set()
            break


def main():
    while True:
        mode = input("\nSelect mode (server/client/exit): ")
        if mode == 'server':
            local_host = input("Enter host to bind (default 'localhost'): ") or 'localhost'
            port_input = input("Enter port to bind (default 65432): ") or '65432'
            try:
                local_port = int(port_input)
                start_server(local_host, local_port)
            except ValueError:
                print("Invalid port number.")
                
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
                print("Invalid port number.")

        elif mode == 'exit':
            print("Exiting program.")
            break

        else:
            print("Invalid mode selected.")

if __name__ == "__main__":
    main()
