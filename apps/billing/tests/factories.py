import factory

from apps.billing.models import Plan


class PlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Plan
        django_get_or_create = ["code"]

    code = factory.Sequence(lambda n: f"plan-{n}")
    name = factory.LazyAttribute(lambda o: o.code.title())
    amount = 3000
    currency = "usd"
    interval = Plan.Interval.MONTH
    included_units = 10_000
    overage_unit_amount = 50
    overage_unit_size = 1000
