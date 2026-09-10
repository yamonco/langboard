class ScimProvisioningException:
    class Default(Exception):
        pass

    class InvalidRequest(Default):
        pass

    class Conflict(Default):
        pass

    class IdentityLinkRequired(Conflict):
        pass

    class ExternalIdentityConflict(Conflict):
        pass

    class Unavailable(Default):
        pass
