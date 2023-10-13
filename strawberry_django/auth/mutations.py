from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Type, cast

import strawberry
from asgiref.sync import async_to_sync
from channels import auth as channels_auth
from django.contrib import auth
from django.contrib.auth.password_validation import validate_password

from strawberry_django.auth.utils import get_current_user
from strawberry_django.mutations import mutations, resolvers
from strawberry_django.mutations.fields import DjangoCreateMutation
from strawberry_django.optimizer import DjangoOptimizerExtension
from strawberry_django.resolvers import django_resolver
from strawberry_django.utils.requests import get_request

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from strawberry.types import Info


@django_resolver
def resolve_login(info: Info, username: str, password: str) -> AbstractBaseUser | None:
    request = get_request(info)
    user = auth.authenticate(request, username=username, password=password)

    if user is not None:
        try:
            auth.login(request, user)
        except AttributeError:
            # ASGI in combo with websockets needs the channels login functionality.
            # to ensure we're talking about channels, let's veriy that our
            # request is actually channelsrequest
            scope = request.consumer.scope
            async_to_sync(channels_auth.login)(scope, user)
            # According to channels docs you must save the session
            scope["session"].save()
        return user

    # FIXME: Why call logout inside login??
    auth.logout(request)
    return None


@django_resolver
def resolve_logout(info: Info) -> bool:
    user = get_current_user(info)
    ret = user.is_authenticated

    try:
        request = get_request(info)
        auth.logout(request)
    except AttributeError:
        scope = request.consumer.scope
        async_to_sync(channels_auth.logout)(scope)

    return ret


class DjangoRegisterMutation(DjangoCreateMutation):
    def create(self, data: dict[str, Any], *, info: Info):
        model = cast(Type["AbstractBaseUser"], self.django_model)
        assert model is not None

        password = data.pop("password")
        validate_password(password)

        # Do not optimize anything while retrieving the object to update
        with DjangoOptimizerExtension.disabled():
            return resolvers.create(
                info,
                model,
                data,
                full_clean=self.full_clean,
                pre_save_hook=lambda obj: obj.set_password(password),
            )


login = functools.partial(strawberry.mutation, resolver=resolve_login)
logout = functools.partial(strawberry.mutation, resolver=resolve_logout)
register = mutations.create if TYPE_CHECKING else DjangoRegisterMutation
