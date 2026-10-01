import factory

from apps.accounts.tests.factories import UserFactory
from apps.organizations.models import Membership, Organization, Role


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Acme {n}")
    billing_email = factory.LazyAttribute(lambda o: f"billing@{o.name.lower().replace(' ', '')}.io")


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership

    organization = factory.SubFactory(OrganizationFactory)
    user = factory.SubFactory(UserFactory)
    role = Role.MEMBER
