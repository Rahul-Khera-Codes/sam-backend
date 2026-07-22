import unittest

from app.services.hr_interview_compliance_service import deterministic_check


class InterviewComplianceTests(unittest.TestCase):
    def test_blocks_age_question(self):
        result = deterministic_check("How old are you?")
        self.assertFalse(result.allowed)
        self.assertIn("age", result.categories)
        self.assertIn("protected characteristics", result.reason)

    def test_blocks_salary_history_question(self):
        result = deterministic_check("What was your previous salary?")
        self.assertFalse(result.allowed)
        self.assertIn("salary_history", result.categories)
        self.assertIn("restricted in many jurisdictions", result.reason)

    def test_blocks_family_planning_question(self):
        result = deterministic_check("Do you plan to have children?")
        self.assertFalse(result.allowed)
        self.assertIn("pregnancy_family", result.categories)

    def test_allows_work_authorization_question(self):
        result = deterministic_check(
            "Are you legally authorized to work in the country where this role is based?"
        )
        self.assertTrue(result.allowed)

    def test_allows_job_related_behavioral_question(self):
        result = deterministic_check(
            "Describe a difficult technical problem you solved and how you measured success."
        )
        self.assertTrue(result.allowed)


if __name__ == "__main__":
    unittest.main()
