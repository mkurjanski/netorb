# NetOrb

## Project

**netorb** — simple network observability tool in Django. 

## Tech Stack
- Python 3.12, Django 5.x
- PostgreSQL (local dev via Docker)
- Django REST Framework for API endpoints
- pytest-django for tests

## Project Structure
- `netorb/` - main Django app
- `netorb/models.py` - data models
- `netorb/views.py` - views and API endpoints
- `netorb/tests/` - test files

## Commands
- Run server: `python manage.py runserver`
- Run tests: `pytest`
- Make migrations: `python manage.py makemigrations`
- Apply migrations: `python manage.py migrate`

## Code Rules
- Always write a test for new models and views
- Use class-based views for CRUD operations
- Keep views thin — business logic goes in service functions
- Never commit secrets; use python-decouple for env vars

## Django Conventions
- Models use verbose_name and help_text on fields
- All API endpoints return consistent JSON using DRF serializers
```