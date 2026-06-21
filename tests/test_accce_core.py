import os
import tempfile
import unittest
from pydantic import ValidationError

from project_accce.schemas import SyllabusNode, QuizPayload
from project_accce.behavior.math_utils import get_poisson_delay
from project_accce.behavior.mouse import generate_bezier_points
from project_accce.orchestrator.db import ACCCEStorage

class TestACCCECore(unittest.TestCase):
    def test_pydantic_schemas_validation(self):
        # Test valid syllabus node
        node = SyllabusNode(id="test-1", type="video", is_completed=False)
        self.assertEqual(node.id, "test-1")
        self.assertEqual(node.type, "video")
        self.assertFalse(node.is_completed)

        # Test invalid syllabus node (missing type)
        with self.assertRaises(ValidationError):
            SyllabusNode(id="test-2")

        # Test valid quiz payload
        quiz = QuizPayload(
            question_text="What is 2+2?",
            question_type="multiple_choice",
            options_array=["3", "4", "5"],
            input_element_selectors=["input.o1", "input.o2", "input.o3"]
        )
        self.assertEqual(quiz.question_type, "multiple_choice")

        # Test invalid quiz payload (missing fields)
        with self.assertRaises(ValidationError):
            QuizPayload(question_text="Fail")

    def test_poisson_delay_calculation(self):
        # Run multiple iterations and verify they conform to bounds and have variation
        delays = [get_poisson_delay(mean_delay=2.0, min_bounds=0.5, max_bounds=5.0) for _ in range(50)]
        
        for d in delays:
            self.assertTrue(0.5 <= d <= 5.0)

        # Ensure there is variation (it's not a static or single constant)
        self.assertTrue(len(set(delays)) > 10)

    def test_bezier_points_generation(self):
        start = (10.0, 10.0)
        end = (100.0, 100.0)
        steps = 20
        
        points = generate_bezier_points(start, end, steps)
        
        self.assertEqual(len(points), steps + 1)
        self.assertEqual(points[0], start)
        # End point is easing-interpolated exactly to end_pos
        self.assertTrue(abs(points[-1][0] - end[0]) < 0.1)
        self.assertTrue(abs(points[-1][1] - end[1]) < 0.1)

    def test_sqlite_session_and_state_persistence(self):
        # Use a temporary file for database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
            
        try:
            db = ACCCEStorage(db_path)
            
            # Test session save and retrieve
            test_cookies = [{"name": "auth_token", "value": "xyz123", "domain": "coursera.org"}]
            test_storage = {"active_course": "machine-learning"}
            
            db.save_session("course-xyz", test_cookies, test_storage)
            session = db.get_session("course-xyz")
            
            self.assertIsNotNone(session)
            self.assertEqual(session["cookies"][0]["value"], "xyz123")
            self.assertEqual(session["local_storage"]["active_course"], "machine-learning")
            
            # Test course state
            db.save_course_state("course-xyz", "node-3", ["node-1", "node-2"])
            state = db.get_course_state("course-xyz")
            
            self.assertIsNotNone(state)
            self.assertEqual(state["current_node_id"], "node-3")
            self.assertIn("node-1", state["completed_nodes"])
            
            # Test peer review
            db.save_peer_review("course-xyz", "node-4", "sub-1234", 1, 2, "reviewing")
            review = db.get_peer_review("sub-1234")
            
            self.assertIsNotNone(review)
            self.assertEqual(review["node_id"], "node-4")
            self.assertEqual(review["status"], "reviewing")
            
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

if __name__ == "__main__":
    unittest.main()
