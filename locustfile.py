from locust import HttpUser, task, between

class SkilliflyUser(HttpUser):
    wait_time = between(1, 3)

    @task(5)
    def view_index(self):
        self.client.get("/")

    @task(2)
    def view_themes(self):
        self.client.get("/themes/")

    @task(1)
    def view_payment(self):
        self.client.get("/payment/")

    @task(1)
    def view_contact(self):
        self.client.get("/contact/")

    @task(1)
    def view_terms(self):
        self.client.get("/terms/")
