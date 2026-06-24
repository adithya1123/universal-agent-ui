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

    mlflow_experiment_id: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
