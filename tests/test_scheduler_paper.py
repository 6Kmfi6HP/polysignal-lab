"""
Input: None
Output: None
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



# Legacy scheduler process_signal has been disabled along with the rest of the
# scheduler_processing module (only evaluate_once with its RuntimeError guard
# remains).  These tests exercised the old signal storage/publish path and are
# no longer applicable.
