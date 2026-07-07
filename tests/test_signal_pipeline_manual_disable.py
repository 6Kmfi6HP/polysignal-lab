"""
Input: None
Output: None
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



# Legacy scheduler evaluation (evaluate_candidates_ordered) has been disabled.
# The signal pipeline unit tests that exercised strategy disable/dependency logic
# through scheduler_processing were tied to the removed entry point and have been
# removed accordingly. The signal pipeline behavior is covered by integration tests
# that construct a full PolySignalScheduler.
