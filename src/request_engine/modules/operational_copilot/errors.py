class CopilotSemanticError(ValueError):
    pass


class UnsupportedCopilotIntent(CopilotSemanticError):
    pass


class AmbiguousCopilotIntent(CopilotSemanticError):
    pass


class CopilotPolicyRejected(CopilotSemanticError):
    pass
