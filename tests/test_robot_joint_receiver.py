from __future__ import annotations

import math
import socket
import threading
import unittest

from app.robot_joint_receiver import parse_joint_line
from app.tcp_sender import TcpJsonLineClient, TcpTarget


class RobotJointReceiverParsingTest(unittest.TestCase):
    def test_parse_pos_deg_json(self) -> None:
        frame = parse_joint_line('{"pos_deg":[0,60,-60,0,0,0]}')
        self.assertEqual(frame.unit, "deg")
        self.assertAlmostEqual(frame.pos_rad[1], math.radians(60), places=6)

    def test_parse_pos_rad_json(self) -> None:
        frame = parse_joint_line('{"pos_rad":[0,1.047,-1.047,0,0,0]}')
        self.assertEqual(frame.unit, "rad")
        self.assertAlmostEqual(frame.pos_deg[1], math.degrees(1.047), places=4)

    def test_parse_joints_with_unit(self) -> None:
        frame = parse_joint_line('{"joints":[0,60,-60,0,0,0],"unit":"deg"}')
        self.assertEqual(frame.unit, "deg")
        self.assertAlmostEqual(frame.pos_deg[2], -60, places=4)

    def test_parse_csv_default_deg(self) -> None:
        frame = parse_joint_line("0,60,-60,0,0,0")
        self.assertEqual(frame.unit, "deg")
        self.assertAlmostEqual(frame.pos_rad[1], math.radians(60), places=6)

    def test_rejects_wrong_value_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly six"):
            parse_joint_line("0,1,2")

    def test_rejects_non_numeric_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "numeric"):
            parse_joint_line("0,1,nope,3,4,5")

    def test_rejects_invalid_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            parse_joint_line('{"pos_deg":[0,1,2]')

    def test_clamps_to_a1z_limits(self) -> None:
        frame = parse_joint_line('{"pos_deg":[999,999,-999,999,999,999]}')
        self.assertAlmostEqual(frame.pos_rad[0], 2.094, places=6)
        self.assertAlmostEqual(frame.pos_rad[1], 3.142, places=6)
        self.assertAlmostEqual(frame.pos_rad[2], -3.142, places=6)
        self.assertAlmostEqual(frame.pos_rad[3], 1.309, places=6)
        self.assertAlmostEqual(frame.pos_rad[4], 1.484, places=6)
        self.assertAlmostEqual(frame.pos_rad[5], 2.007, places=6)


if __name__ == "__main__":
    unittest.main()


class TcpJsonLineClientReadbackTest(unittest.TestCase):
    def test_reads_line_from_same_socket_used_for_send(self) -> None:
        received_payload = []
        received_lines = []
        ready = threading.Event()

        def server(listener: socket.socket) -> None:
            ready.set()
            conn, _ = listener.accept()
            with conn:
                received_payload.append(conn.recv(4096))
                conn.sendall(b'{"pos_deg":[0,60,-60,0,0,0]}\n')

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            thread = threading.Thread(target=server, args=(listener,), daemon=True)
            thread.start()
            self.assertTrue(ready.wait(1.0))
            client = TcpJsonLineClient(TcpTarget("127.0.0.1", port, 1.0), on_line=received_lines.append)
            client.send({"status": "home"})
            thread.join(1.0)
            client.close()

        self.assertIn(b'{"status":"home"}', received_payload[0])
        self.assertEqual(received_lines, ['{"pos_deg":[0,60,-60,0,0,0]}'])
