from __VERSION import VERSION
from .avatar import get_avatar_color, get_gravatar_url, get_initials
from .models import OperatorProfile


def project_version(request):
    return {
        'VERSION': VERSION,
    }


def operator_avatar(request):
    """Supplies the topnav's operator display name and avatar, matching Register's own topnav
    (name, then avatar - Gravatar or initials, depending on the cached OperatorProfile's
    avatar_type). A local-only account (e.g. createsuperuser) has no OperatorProfile, so this
    falls back to Django's own get_full_name()/get_username()."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}

    try:
        profile = user.operator_profile
    except OperatorProfile.DoesNotExist:
        profile = None

    full_name = profile.full_name if profile else user.get_full_name()
    display_name = full_name or user.get_short_name() or user.get_username()
    use_gravatar = bool(profile and profile.avatar_type == 'gravatar')

    return {
        'operator_display_name': display_name,
        'operator_avatar_url': get_gravatar_url(user.email) if use_gravatar else None,
        'operator_initials': get_initials(full_name, user.email),
        'operator_avatar_color': get_avatar_color(user.email),
    }
