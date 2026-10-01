from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Membership, Organization, Role

User = get_user_model()


class OrganizationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "billing_email", "currency", "role", "created_at"]
        read_only_fields = ["id", "slug", "role", "created_at"]

    def get_role(self, org) -> str | None:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        membership = next((m for m in org.memberships.all() if m.user_id == request.user.pk), None)
        return membership.role if membership else None

    def validate_currency(self, value: str) -> str:
        value = value.lower()
        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError("Use a 3-letter ISO currency code.")
        return value


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True)
    user = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "email", "user", "role", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def get_user(self, membership) -> dict:
        return {"id": membership.user_id, "email": membership.user.email}

    def validate_email(self, value):
        user = User.objects.filter(email=value.lower()).first()
        if user is None:
            raise serializers.ValidationError("No user with this email. Ask them to sign up first.")
        if Membership.objects.filter(organization=self.context["organization"], user=user).exists():
            raise serializers.ValidationError("This user is already a member.")
        return user

    def validate_role(self, role):
        actor = self.context["view"].membership
        if role == Role.OWNER and actor.role != Role.OWNER:
            raise serializers.ValidationError("Only owners can grant the owner role.")
        return role

    def create(self, validated_data):
        return Membership.objects.create(
            organization=self.context["organization"],
            user=validated_data["email"],
            role=validated_data.get("role", Role.MEMBER),
        )


class MembershipUpdateSerializer(MembershipSerializer):
    class Meta(MembershipSerializer.Meta):
        fields = ["id", "user", "role", "created_at"]
