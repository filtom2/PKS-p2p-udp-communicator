import socket
import threading
import zlib
import time
import os

# Message Types
MSG_DEFAULT = 0
MSG_SYN = 1
MSG_SYN_ACK = 2
MSG_ACK = 3
MSG_FIN = 4
MSG_KEEP_ALIVE = 5
MSG_FRAGMENT = 6
MSG_LAST_FRAGMENT = 7
MSG_FILE_DEFAULT = 8
MSG_FILE_FRAGMENT = 9
MSG_FILE_LAST_FRAGMENT = 10

def create_message(msg_type, sequence_number, data=b''):
    crc = zlib.crc32(data)
    crc_bytes = crc.to_bytes(4, 'big')
    sequence_bytes = sequence_number.to_bytes(2, 'big')
    return bytes([msg_type]) + sequence_bytes + crc_bytes + data

def parse_message_with_sequence(message):
    msg_type = message[0]
    sequence_number = int.from_bytes(message[1:3], 'big')
    received_crc = int.from_bytes(message[3:7], 'big')
    data = message[7:]
    if zlib.crc32(data) != received_crc:
        print("Warning: CRC mismatch!")
        return None, None, None
    return msg_type, data, sequence_number

def keep_alive(sock, addr, stop_event, lost_connection_event, interval=5):
    while not stop_event.is_set():
        time.sleep(interval)
        sock.sendto(create_message(MSG_KEEP_ALIVE, 0), addr)

        if lost_connection_event.is_set():
            stop_event.set()
            break

def receive_messages(sock, stop_event, lost_connection_event, addr, interval=5, buffer_size=1024):
    last_activity = time.time()
    fragment_buffers = {}  # Dictionary to store fragments by message ID
    message_sizes = {}     # Dictionary to store total size per message ID
    num_fragments_received = {}  # Dictionary to store number of fragments received per message ID
    message_start_times = {}  # Record when the first fragment was received
    message_types = {}  # Store message type per message ID

    while not stop_event.is_set():
        try:
            sock.settimeout(interval)
            data, _ = sock.recvfrom(buffer_size)
            if data:
                msg_type, msg_data, sequence_number = parse_message_with_sequence(data)
                if msg_type == MSG_FIN:
                    print("Peer has closed the connection.")
                    stop_event.set()
                    break
                elif msg_type == MSG_KEEP_ALIVE:
                    last_activity = time.time()  # Reset activity timer on Keep-Alive
                elif msg_type in (MSG_DEFAULT, MSG_FRAGMENT, MSG_LAST_FRAGMENT,
                                  MSG_FILE_DEFAULT, MSG_FILE_FRAGMENT, MSG_FILE_LAST_FRAGMENT):
                    last_activity = time.time()
                    # Extract message_id and fragment_number from sequence_number
                    message_id = sequence_number >> 8  # Upper 8 bits
                    fragment_number = sequence_number & 0xFF  # Lower 8 bits

                    if message_id not in fragment_buffers:
                        fragment_buffers[message_id] = {}
                        num_fragments_received[message_id] = 0
                        message_sizes[message_id] = 0
                        # Record the start time for this message
                        message_start_times[message_id] = time.time()
                        # Store the message type
                        message_types[message_id] = msg_type

                    fragment_buffers[message_id][fragment_number] = msg_data
                    num_fragments_received[message_id] += 1
                    message_sizes[message_id] += len(msg_data)

                    if msg_type in (MSG_DEFAULT, MSG_FILE_DEFAULT):
                        # Single message, no fragmentation
                        complete_message = msg_data
                        elapsed_time = time.time() - message_start_times[message_id]
                        if msg_type == MSG_DEFAULT:
                            print(f"[Peer {addr}] {complete_message.decode()}")
                            print(f"Received message: Name=message, Size={len(complete_message)} bytes, Fragments=1, Time={elapsed_time:.2f}s")
                        else:
                            # Handle file
                            title, content = complete_message.split(b'\0', 1)
                            file_name = title.decode()
                            with open(file_name, 'wb') as f:
                                f.write(content)
                            print(f"Received file: Name={file_name}, Size={len(content)} bytes, Fragments=1, Time={elapsed_time:.2f}s")
                        # Clean up
                        del fragment_buffers[message_id]
                        del num_fragments_received[message_id]
                        del message_sizes[message_id]
                        del message_start_times[message_id]
                        del message_types[message_id]
                    elif msg_type in (MSG_LAST_FRAGMENT, MSG_FILE_LAST_FRAGMENT):
                        # Last fragment received, reassemble message
                        fragments = fragment_buffers[message_id]
                        # Sort fragments by fragment_number
                        ordered_fragments = [fragments[i] for i in sorted(fragments)]
                        complete_message = b''.join(ordered_fragments)
                        total_size = message_sizes[message_id]
                        num_fragments = num_fragments_received[message_id]
                        elapsed_time = time.time() - message_start_times[message_id]
                        if message_types[message_id] in (MSG_DEFAULT, MSG_FRAGMENT, MSG_LAST_FRAGMENT):
                            # Text message
                            print(f"[Peer {addr}] {complete_message.decode()}")
                            print(f"Received message: Name=message, Size={total_size} bytes, Fragments={num_fragments}, Time={elapsed_time:.2f}s")
                        else:
                            # File message
                            title, content = complete_message.split(b'\0', 1)
                            file_name = title.decode()
                            with open(file_name, 'wb') as f:
                                f.write(content)
                            print(f"Received file: Name={file_name}, Size={len(content)} bytes, Fragments={num_fragments}, Time={elapsed_time:.2f}s")
                        # Clean up
                        del fragment_buffers[message_id]
                        del num_fragments_received[message_id]
                        del message_sizes[message_id]
                        del message_start_times[message_id]
                        del message_types[message_id]
                    else:
                        # Continue receiving fragments
                        pass
                else:
                    print(f"Unknown message type: {msg_type}")
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
            if time.time() - last_activity > interval * 3:  # 3 times checks
                print("Connection lost due to inactivity.")
                lost_connection_event.set()
                stop_event.set()
                break
        except Exception as e:
            print(f"Receiving error: {e}")
            stop_event.set()
            break

def handle_handshake_server(server_sock):
    data, addr = server_sock.recvfrom(1024)
    msg_type, _, _ = parse_message_with_sequence(data)
    if msg_type == MSG_SYN:
        server_sock.sendto(create_message(MSG_SYN_ACK, 0), addr)
        data, addr = server_sock.recvfrom(1024)
        msg_type, _, _ = parse_message_with_sequence(data)
        if msg_type == MSG_ACK:
            print(f"\nHandshake complete with client at {addr}\n")
            return addr
    return None

def handle_handshake_client(client_sock, server_address):
    client_sock.sendto(create_message(MSG_SYN, 0), server_address)
    data, _ = client_sock.recvfrom(1024)
    msg_type, _, _ = parse_message_with_sequence(data)
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
    sequence_number = 0  # Initialize sequence number
    message_id_counter = 0  # Initialize message ID counter

    while not stop_event.is_set():
        try:
            max_data_size_input = input("Enter the minimal fragmentation size (bytes): ")
            try:
                MAX_DATA_SIZE = int(max_data_size_input)
                if MAX_DATA_SIZE <= 0:
                    print("Fragmentation size must be a positive integer.")
                    continue
            except ValueError:
                print("Invalid input. Please enter a positive integer.")
                continue

            choice = input("Do you want to send a text message or a file? (text/file/exit): ").lower()
            if choice == 'exit':
                sock.sendto(create_message(MSG_FIN, 0), addr)
                stop_event.set()
                break
            elif choice == 'text':
                message = input("Enter your message: ")
                message_bytes = message.encode()
                total_size = len(message_bytes)
                if total_size <= MAX_DATA_SIZE:
                    # Send as a single message
                    sock.sendto(create_message(MSG_DEFAULT, sequence_number, message_bytes), addr)
                    # Display info
                    print(f"Sent message: Name=message, Size={total_size} bytes, Fragments=1")
                    sequence_number = (sequence_number + 1) % 65536
                else:
                    # Fragment the message
                    fragments = [message_bytes[i:i+MAX_DATA_SIZE] for i in range(0, total_size, MAX_DATA_SIZE)]
                    num_fragments = len(fragments)
                    message_id = message_id_counter
                    message_id_counter = (message_id_counter + 1) % 256  # Keep it within 8 bits

                    for i, fragment in enumerate(fragments):
                        if i == num_fragments - 1:
                            # Last fragment
                            msg_type = MSG_LAST_FRAGMENT
                        else:
                            msg_type = MSG_FRAGMENT

                        fragment_number = i  # Fragment index
                        # Construct sequence_number with message_id and fragment_number
                        sequence_number = (message_id << 8) | fragment_number
                        sock.sendto(create_message(msg_type, sequence_number, fragment), addr)
                    # Display info
                    print(f"Sent message: Name=message, Size={total_size} bytes, Fragments={num_fragments}")
            elif choice == 'file':
                file_path = input("Enter the file path: ")
                title = input("Enter the file title to send: ")
                if not os.path.isfile(file_path):
                    print("File does not exist. Please provide a valid file path.")
                    continue
                with open(file_path, 'rb') as f:
                    file_content = f.read()
                # Prepend the title to the content, separated by a null byte
                title_bytes = title.encode()
                combined_data = title_bytes + b'\0' + file_content
                total_size = len(combined_data)
                if total_size <= MAX_DATA_SIZE:
                    # Send as a single message
                    sock.sendto(create_message(MSG_FILE_DEFAULT, sequence_number, combined_data), addr)
                    print(f"Sent file: Name={title}, Size={total_size} bytes, Fragments=1")
                    sequence_number = (sequence_number + 1) % 65536
                else:
                    # Fragment the file
                    fragments = [combined_data[i:i+MAX_DATA_SIZE] for i in range(0, total_size, MAX_DATA_SIZE)]
                    num_fragments = len(fragments)
                    message_id = message_id_counter
                    message_id_counter = (message_id_counter + 1) % 256  # Keep it within 8 bits

                    for i, fragment in enumerate(fragments):
                        if i == num_fragments - 1:
                            # Last fragment
                            msg_type = MSG_FILE_LAST_FRAGMENT
                        else:
                            msg_type = MSG_FILE_FRAGMENT

                        fragment_number = i  # Fragment index
                        # Construct sequence_number with message_id and fragment_number
                        sequence_number = (message_id << 8) | fragment_number
                        sock.sendto(create_message(msg_type, sequence_number, fragment), addr)
                    print(f"Sent file: Name={title}, Size={total_size} bytes, Fragments={num_fragments}")
            else:
                print("Invalid choice. Please enter 'text', 'file', or 'exit'.")
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
