from __VERSION import VERSION


def project_version(request):
    return {
        'VERSION': VERSION,
    }
