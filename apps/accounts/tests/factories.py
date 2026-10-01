import factory

from apps.accounts.models import User

DEFAULT_PASSWORD = "S3cure-pass!"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    full_name = factory.Faker("name")
    password = factory.django.Password(DEFAULT_PASSWORD)
