# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**netorb** — simple network observability tool built with Django.

## Tech Stack

- Python 3.12, Django 5.x
- PostgreSQL (local dev via Docker)
- Django REST Framework for API endpoints
- pytest-django for tests
- python-decouple for environment variables

## Commands

- Run server: `python manage.py runserver`
- Run all tests: `pytest`
- Run a single test: `pytest netorb/tests/test_foo.py::TestClass::test_method`
- Make migrations: `python manage.py makemigrations`
- Apply migrations: `python manage.py migrate`

## Architecture

`netorb/` is the main Django app. Business logic lives in service functions (not in views). Views are class-based and kept thin. All API endpoints use DRF serializers for consistent JSON responses.

## Conventions

- Models use `verbose_name` and `help_text` on fields
- Use class-based views for CRUD operations
- Business logic goes in service functions, not views
