# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 SuperHouse Automation Pty Ltd <info@superhouse.tv>
from django.urls import path

from test_suites import views

app_name = 'test_suites'

urlpatterns = [
    path('', views.test_suite_list, name='list'),
    path('update/', views.test_suite_update, name='update'),
    path('<int:suite_id>/fetch/', views.test_suite_fetch, name='fetch'),
    path('<int:pk>/', views.test_suite_detail, name='detail'),
    path('<int:pk>/run/', views.test_suite_run, name='run'),
]
