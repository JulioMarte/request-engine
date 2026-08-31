class CopilotSemanticError(ValueError):
    pass


class UnsupportedCopilotIntent(CopilotSemanticError):
    pass


class AmbiguousCopilotIntent(CopilotSemanticError):
    pass


class CopilotPolicyRejected(CopilotSemanticError):
    pass


class CopilotResolutionFailed(CopilotSemanticError):
    pass


class CopilotConflict(RuntimeError):
    pass
