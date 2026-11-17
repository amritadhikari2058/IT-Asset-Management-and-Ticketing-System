from django.test import TestCase
from django.db import connection
from rest_framework.test import APIClient
from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory, AssetAttachment
from django.core.files.uploadedfile import SimpleUploadedFile

class DbgTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.acat = AssetCategory.objects.create(name="Laptop")
        self.asset = Asset.objects.create(asset_tag="AT1", name="n", category=self.acat, assigned_to=self.emp, status="assigned")
        auth(self.c, self.mgr)
    def _upload_file(self):
        return SimpleUploadedFile("d.txt", b"hi", content_type="text/plain")
    def test_upload(self):
        res = self.c.post("/api/assets/attachments/", {"asset": self.asset.pk, "file": self._upload_file()}, format="multipart")
        print("upload status", res.status_code)
        print("conn is None?", connection.connection is None)
        print("in_atomic", connection.in_atomic_block)
    def tearDown(self):
        print("tearDown conn is None?", connection.connection is None)
