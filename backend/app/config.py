from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    databricks_host: str = ""
    databricks_client_id: str = ""
    databricks_client_secret: str = ""
    databricks_token: str = ""
    databricks_config_profile: str = ""

    lakebase_instance_name: str = ""
    lakebase_autoscaling_project: str = ""
    lakebase_autoscaling_branch: str = ""
    lakebase_url: str = ""

    result_volume_path: str = ""

    embedding_endpoint: str = ""
    embedding_dims: int = 0

    max_history: int = 10
    supervisor_timeout: int = 300
    auto_approve_tools: bool = True

    memory_extraction_enabled: bool = True
    memory_extraction_model: str = "deepseek-v4flash-chat"
    memory_max_per_user: int = 100
    memory_max_value_size: int = 4096
    memory_injection_max: int = 10
    memory_extraction_cooldown_minutes: int = 5
    memory_extraction_min_message_length: int = 50
    memory_extraction_window: int = 10
    memory_ttl_days: int = 90
    memory_ttl_min_access: int = 2

    mlflow_tracking_uri: str = "databricks"
    mlflow_experiment_id: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
