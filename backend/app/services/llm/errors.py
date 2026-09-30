"""LLM 异常体系：全部携带可直接展示给用户的中文 message。

全局异常处理器（main.py）捕获 LLMError 统一返回 400 + {"detail": message}。
"""


class LLMError(Exception):
    """业务可展示的 LLM 错误基类。"""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


class LLMNotConfiguredError(LLMError):
    def __init__(self):
        super().__init__(
            "尚未配置 LLM 服务，请先到「设置」页填写 base_url、API Key 和模型名。"
        )


class LLMConnectionError(LLMError):
    def __init__(self, detail: str = ""):
        super().__init__("无法连接到 LLM 服务，请检查 base_url 与网络。", detail)


class LLMAuthError(LLMError):
    def __init__(self, detail: str = ""):
        super().__init__("LLM 服务鉴权失败，请检查 API Key 是否正确。", detail)


class LLMRateLimitError(LLMError):
    def __init__(self, detail: str = ""):
        super().__init__("LLM 服务限流或额度不足，请稍后重试。", detail)


class LLMServiceError(LLMError):
    def __init__(self, detail: str = ""):
        super().__init__("LLM 服务返回错误，请稍后重试或更换模型。", detail)


class LLMParseError(LLMError):
    def __init__(self, detail: str = ""):
        super().__init__("模型输出无法解析为结构化数据，已重试仍失败，请重试一次。", detail)
