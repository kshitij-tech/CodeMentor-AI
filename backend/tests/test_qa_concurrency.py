
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.tests.qa_support import (
    TestDatabase,
    SyncASGIClient,
    add_problem,
    add_user,
    auth_headers,
    auth_token,
    build_test_app,
    reset_catalog_cache,
)


class ConcurrentRequestQualityTests(unittest.TestCase):
    def setUp(self):
        reset_catalog_cache()
        self.database = TestDatabase()
        self.db = self.database.session()
        self.app = build_test_app(self.database)
        self.client = SyncASGIClient(self.app)
        self.problem = add_problem(self.db, slug="concurrent-request")
        self.users = [
            add_user(self.db, f"request-user-{index}@example.com")
            for index in range(6)
        ]

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.database.close()
        reset_catalog_cache()

    def test_concurrent_workspace_requests_remain_user_isolated(self):
        def save_for_user(index):
            user = self.users[index]
            response = self.client.request(
                "PUT",
                "/workspace",
                headers=auth_headers(auth_token(user)),
                json_body={
                    "problem_slug": self.problem.slug,
                    "language": "Python",
                    "code": f"print('user-{index}')",
                },
            )
            return index, response

        with ThreadPoolExecutor(max_workers=len(self.users)) as pool:
            results = list(pool.map(save_for_user, range(len(self.users))))

        for index, response in results:
            self.assertEqual(response.status_code, 200, response.json)

        for index, user in enumerate(self.users):
            response = self.client.request(
                "GET",
                f"/workspace?problem_slug={self.problem.slug}&language=Python",
                headers=auth_headers(auth_token(user)),
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["code"], f"print('user-{index}')")


if __name__ == "__main__":
    unittest.main()
