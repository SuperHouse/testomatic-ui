from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from __VERSION import VERSION


class VersionDisplayTest(TestCase):
    def test_version_is_displayed_in_sidebar(self):
        user = get_user_model().objects.create_user(username='testuser', password='secret123')
        self.client.force_login(user)

        response = self.client.get(reverse('home'))

        self.assertContains(response, VERSION)
        self.assertContains(response, 'sidebar-version')
