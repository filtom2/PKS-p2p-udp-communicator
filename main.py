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
MSG_FILE_INFO = 8
MSG_FILE_FRAGMENT = 9
MSG_FILE_LAST_FRAGMENT = 10
MSG_FRAGMENT_ACK = 11  # New message type for fragment acknowledgment


def create_message(msg_type, sequence_number, data=b''):
    crc = zlib.crc32(data)
    crc_bytes = crc.to_bytes(4, 'big')
    sequence_bytes = sequence_number.to_bytes(4, 'big') 
    return bytes([msg_type]) + sequence_bytes + crc_bytes + data


def parse_message_with_sequence(message):
    msg_type = message[0]
    sequence_number = int.from_bytes(message[1:5], 'big')  # Updated to 4 bytes
    received_crc = int.from_bytes(message[5:9], 'big')     # Adjusted index
    data = message[9:]                                     # Adjusted index
    if zlib.crc32(data) != received_crc:
        print("Warning: CRC mismatch!")
        return None, None, None
    return msg_type, data, sequence_number


def keep_alive(sock, addr, stop_event, lost_connection_event, display_keep_alive, interval=5):
    while not stop_event.is_set():
        time.sleep(interval)
        sock.sendto(create_message(MSG_KEEP_ALIVE, 0), addr)
        if display_keep_alive:
            print(f"Sending keep-alive packet to {addr}")

        if lost_connection_event.is_set():
            stop_event.set()
            break


def receive_messages(sock, stop_event, lost_connection_event, addr, save_directory, display_keep_alive, acknowledged_sequences, ack_condition, interval=5, buffer_size=2048):
    last_activity = time.time()
    message_buffers = {}  # Dictionary to store messages by message ID

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
                    if display_keep_alive:
                        print(f"Received keep-alive packet from {addr}")
                elif msg_type == MSG_FILE_INFO:
                    last_activity = time.time()
                    # Extract file_name_length, file_name, file_size
                    file_name_length = msg_data[0]
                    file_name = msg_data[1:1+file_name_length].decode()
                    file_size = int.from_bytes(msg_data[1+file_name_length:1+file_name_length+4], 'big')
                    # Prepare to receive file data
                    message_id = sequence_number >> 16  # Upper 16 bits
                    message_buffers[message_id] = {
                        'type': 'file',
                        'fragments': {},
                        'num_fragments_received': 0,
                        'total_size': 0,
                        'start_time': time.time(),
                        'file_name': file_name,
                        'expected_total_size': file_size,
                    }
                    print(f"Receiving file: {file_name}, Size: {file_size} bytes")
                elif msg_type in (MSG_FILE_FRAGMENT, MSG_FILE_LAST_FRAGMENT, MSG_FRAGMENT, MSG_LAST_FRAGMENT):
                    last_activity = time.time()
                    # Extract message_id and fragment_number from sequence_number
                    message_id = sequence_number >> 16    # Upper 16 bits
                    fragment_number = sequence_number & 0xFFFF  # Lower 16 bits

                    if message_id not in message_buffers:
                        if msg_type in (MSG_FILE_FRAGMENT, MSG_FILE_LAST_FRAGMENT):
                            print("Warning: Received file fragment before file info.")
                            continue
                        else:
                            # Initialize buffer for message
                            message_buffers[message_id] = {
                                'type': 'message',
                                'fragments': {},
                                'num_fragments_received': 0,
                                'total_size': 0,
                                'start_time': time.time(),
                            }

                    buffer = message_buffers[message_id]
                    buffer['fragments'][fragment_number] = msg_data
                    buffer['num_fragments_received'] += 1
                    buffer['total_size'] += len(msg_data)

                    # Send ACK back to sender
                    ack_message = create_message(MSG_FRAGMENT_ACK, sequence_number)
                    sock.sendto(ack_message, addr)
                    print(f"Sent ACK for sequence number {sequence_number}")

                    if buffer['type'] == 'file':
                        if msg_type == MSG_FILE_LAST_FRAGMENT:
                            # Last fragment received, reassemble file
                            fragments = buffer['fragments']
                            # Sort fragments by fragment_number
                            ordered_fragments = [fragments[i] for i in sorted(fragments)]
                            complete_data = b''.join(ordered_fragments)
                            total_size = buffer['total_size']
                            num_fragments = buffer['num_fragments_received']
                            elapsed_time = time.time() - buffer['start_time']
                            # Save the file
                            save_path = os.path.join(save_directory, buffer['file_name'])
                            with open(save_path, 'wb') as f:
                                f.write(complete_data)
                            print(f"Received file: Name={buffer['file_name']}, Size={total_size} bytes, Fragments={num_fragments}, Time={elapsed_time:.2f}s")
                            # Clean up
                            del message_buffers[message_id]
                        else:
                            # Continue receiving fragments
                            pass
                    else:
                        # Handle message fragments
                        if msg_type == MSG_LAST_FRAGMENT:
                            # Last fragment received, reassemble message
                            fragments = buffer['fragments']
                            # Sort fragments by fragment_number
                            ordered_fragments = [fragments[i] for i in sorted(fragments)]
                            complete_message = b''.join(ordered_fragments)
                            total_size = buffer['total_size']
                            num_fragments = buffer['num_fragments_received']
                            elapsed_time = time.time() - buffer['start_time']
                            print(f"[Peer {addr}] {complete_message.decode()}")
                            print(f"Received message: Name=message, Size={total_size} bytes, Fragments={num_fragments}, Time={elapsed_time:.2f}s")
                            # Clean up
                            del message_buffers[message_id]
                        else:
                            # Continue receiving fragments
                            pass
                elif msg_type == MSG_DEFAULT:
                    last_activity = time.time()
                    # Single message, no fragmentation
                    print(f"[Peer {addr}] {msg_data.decode()}")
                    print(f"Received message: Name=message, Size={len(msg_data)} bytes, Fragments=1, Time=0.00s")
                elif msg_type == MSG_FRAGMENT_ACK:
                    last_activity = time.time()
                    ack_sequence_number = sequence_number
                    with ack_condition:
                        acknowledged_sequences.add(ack_sequence_number)
                        ack_condition.notify_all()
                    print(f"Received ACK for sequence number {ack_sequence_number}")
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


def handle_handshake_client(client_sock, server_address, max_retries=3, timeout=5):
    client_sock.settimeout(timeout)
    retries = 0
    while retries < max_retries:
        try:
            client_sock.sendto(create_message(MSG_SYN, 0), server_address)
            data, _ = client_sock.recvfrom(1024)
            msg_type, _, _ = parse_message_with_sequence(data)
            if msg_type == MSG_SYN_ACK:
                client_sock.sendto(create_message(MSG_ACK, 0), server_address)
                print("\nHandshake complete with server.\n")
                return True
        except socket.timeout:
            retries += 1
            print(f"Handshake attempt {retries} failed, retrying...")
    print("Handshake failed after maximum retries.")
    return False


def start_server(local_host='localhost', local_port=65432):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_sock:
        try:
            server_sock.bind((local_host, local_port))
            print(f"Server listening on {local_host}:{local_port}")

            save_directory = input("Enter directory to save received files (default '.'): ") or '.'
            if not os.path.exists(save_directory):
                os.makedirs(save_directory)

            display_keep_alive_input = input("Display keep-alive packets? (1 for yes, 0 for no): ") or '0'
            display_keep_alive = display_keep_alive_input == '1'

            stop_event = threading.Event()
            lost_connection_event = threading.Event()

            acknowledged_sequences = set()
            ack_condition = threading.Condition()

            client_address = handle_handshake_server(server_sock)
            if client_address:
                keep_alive_thread = threading.Thread(
                    target=keep_alive,
                    args=(server_sock, client_address, stop_event, lost_connection_event, display_keep_alive),
                    daemon=True
                )
                keep_alive_thread.start()

                recv_thread = threading.Thread(
                    target=receive_messages,
                    args=(server_sock, stop_event, lost_connection_event, client_address, save_directory, display_keep_alive, acknowledged_sequences, ack_condition),
                    daemon=True
                )
                recv_thread.start()

                send_thread = threading.Thread(
                    target=send_messages,
                    args=(server_sock, client_address, stop_event, acknowledged_sequences, ack_condition),
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

            save_directory = input("Enter directory to save received files (default '.'): ") or '.'
            if not os.path.exists(save_directory):
                os.makedirs(save_directory)

            display_keep_alive_input = input("Display keep-alive packets? (1 for yes, 0 for no): ") or '0'
            display_keep_alive = display_keep_alive_input == '1'

            stop_event = threading.Event()
            lost_connection_event = threading.Event()

            acknowledged_sequences = set()
            ack_condition = threading.Condition()

            server_address = (server_host, server_port)

            if handle_handshake_client(client_sock, server_address):
                keep_alive_thread = threading.Thread(
                    target=keep_alive,
                    args=(client_sock, server_address, stop_event, lost_connection_event, display_keep_alive),
                    daemon=True
                )
                keep_alive_thread.start()

                recv_thread = threading.Thread(
                    target=receive_messages,
                    args=(client_sock, stop_event, lost_connection_event, server_address, save_directory, display_keep_alive, acknowledged_sequences, ack_condition),
                    daemon=True
                )
                recv_thread.start()

                send_thread = threading.Thread(
                    target=send_messages,
                    args=(client_sock, server_address, stop_event, acknowledged_sequences, ack_condition),
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

def send_messages(sock, addr, stop_event, acknowledged_sequences, ack_condition):
    sequence_number = 0  # Initialize sequence number
    message_id_counter = 0  # Initialize message ID counter

    while not stop_event.is_set():
        try:
            max_data_size_input = input("Enter the minimal fragmentation size (bytes): ")
            try:
                MAX_DATA_SIZE = int(max_data_size_input)
                if MAX_DATA_SIZE <= 0 or MAX_DATA_SIZE > 144:
                    print("Fragmentation size must be a positive integer up to 1024 bytes.")
                    continue
            except ValueError:
                print("Invalid input. Please enter a positive integer.")
                continue

            message = input("Enter your message ('exit' to quit, 'file' to send a file): ")
            if message.lower() == 'exit':
                sock.sendto(create_message(MSG_FIN, 0), addr)
                stop_event.set()
                break
            elif message.lower() == 'file':
                # Prompt for file path
                file_path = input("Enter the file path to send: ")
                try:
                    with open(file_path, 'rb') as f:
                        file_data = f.read()
                    file_name = os.path.basename(file_path)
                    total_size = len(file_data)
                    # Prepare message ID
                    message_id = message_id_counter
                    message_id_counter = (message_id_counter + 1) % 65536  # Keep it within 16 bits
                    # Send MSG_FILE_INFO message
                    # Data format: file_name_length (1 byte) + file_name + file_size (4 bytes)
                    file_name_bytes = file_name.encode()
                    file_name_length = len(file_name_bytes)
                    if file_name_length > 255:
                        print("File name is too long.")
                        continue
                    file_size_bytes = total_size.to_bytes(4, 'big')
                    data = bytes([file_name_length]) + file_name_bytes + file_size_bytes
                    # Construct sequence_number with message_id (upper 16 bits) and 0 for fragment_number
                    sequence_number = (message_id << 16) | 0
                    sock.sendto(create_message(MSG_FILE_INFO, sequence_number, data), addr)
                    print(f"Sent file info for {file_name}")

                    # Now send the file data, fragmented
                    fragments = [file_data[i:i+MAX_DATA_SIZE] for i in range(0, total_size, MAX_DATA_SIZE)]
                    num_fragments = len(fragments)
                    for i, fragment in enumerate(fragments):
                        if i == num_fragments - 1:
                            msg_type = MSG_FILE_LAST_FRAGMENT
                        else:
                            msg_type = MSG_FILE_FRAGMENT

                        fragment_number = i  # Fragment index
                        if fragment_number > 65535:
                            print("Fragment number exceeds maximum value.")
                            break
                        # Construct sequence_number with message_id and fragment_number
                        sequence_number = (message_id << 16) | fragment_number

                        # Implement stop-and-wait ARQ
                        max_retries = 5
                        retry_count = 0
                        while retry_count < max_retries:
                            # Send the fragment
                            sock.sendto(create_message(msg_type, sequence_number, fragment), addr)
                            print(f"Sent fragment {fragment_number} (Sequence number {sequence_number})")

                            # Wait for ACK
                            with ack_condition:
                                ack_received = ack_condition.wait_for(lambda: sequence_number in acknowledged_sequences, timeout=5)
                                if ack_received:
                                    print(f"ACK received for fragment {fragment_number} (Sequence number {sequence_number})")
                                    acknowledged_sequences.remove(sequence_number)
                                    break  # Proceed to next fragment
                                else:
                                    retry_count += 1
                                    print(f"Timeout waiting for ACK for fragment {fragment_number}, retransmitting (Attempt {retry_count}/5)")
                        else:
                            # Retries exhausted
                            print(f"Failed to receive ACK for fragment {fragment_number} after {max_retries} attempts")
                            stop_event.set()
                            break
                    else:
                        # Display info
                        print(f"Sent file: Name={file_name}, Size={total_size} bytes, Fragments={num_fragments}")
                except Exception as e:
                    print(f"Failed to send file: {e}")
            else:
                # Handle text message
                message_bytes = message.encode()
                total_size = len(message_bytes)
                if total_size <= MAX_DATA_SIZE:
                    # Send as a single message
                    sock.sendto(create_message(MSG_DEFAULT, 0, message_bytes), addr)
                    # Display info
                    print(f"Sent message: Name=message, Size={total_size} bytes, Fragments=1")
                else:
                    # Fragment the message
                    fragments = [message_bytes[i:i+MAX_DATA_SIZE] for i in range(0, total_size, MAX_DATA_SIZE)]
                    num_fragments = len(fragments)
                    # Prepare message ID
                    message_id = message_id_counter
                    message_id_counter = (message_id_counter + 1) % 65536  # Keep it within 16 bits
                    for i, fragment in enumerate(fragments):
                        if i == num_fragments - 1:
                            # Last fragment
                            msg_type = MSG_LAST_FRAGMENT
                        else:
                            msg_type = MSG_FRAGMENT

                        fragment_number = i  # Fragment index
                        if fragment_number > 65535:
                            print("Fragment number exceeds maximum value.")
                            break
                        # Construct sequence_number with message_id and fragment_number
                        sequence_number = (message_id << 16) | fragment_number

                        # Implement stop-and-wait ARQ
                        max_retries = 5
                        retry_count = 0
                        while retry_count < max_retries:
                            # Send the fragment
                            sock.sendto(create_message(msg_type, sequence_number, fragment), addr)
                            print(f"Sent fragment {fragment_number} (Sequence number {sequence_number})")

                            # Wait for ACK
                            with ack_condition:
                                ack_received = ack_condition.wait_for(lambda: sequence_number in acknowledged_sequences, timeout=5)
                                if ack_received:
                                    print(f"ACK received for fragment {fragment_number} (Sequence number {sequence_number})")
                                    acknowledged_sequences.remove(sequence_number)
                                    break  # Proceed to next fragment
                                else:
                                    retry_count += 1
                                    print(f"Timeout waiting for ACK for fragment {fragment_number}, retransmitting (Attempt {retry_count}/5)")
                        else:
                            # Retries exhausted
                            print(f"Failed to receive ACK for fragment {fragment_number} after {max_retries} attempts")
                            stop_event.set()
                            break
                    else:
                        # Display info
                        print(f"Sent message: Name=message, Size={total_size} bytes, Fragments={num_fragments}")
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
