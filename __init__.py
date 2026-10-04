from .nodes import MaxineEyeContact

NODE_CLASS_MAPPINGS = {"MaxineEyeContact": MaxineEyeContact}
NODE_DISPLAY_NAME_MAPPINGS = {"MaxineEyeContact": "NVIDIA Maxine Eye Contact (Local)"}

WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
