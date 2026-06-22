import os
import sys
import logging
from huggingface_hub import HfApi, create_repo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HFDeployer")

HF_TOKEN = os.getenv("HF_TOKEN")
REPO_ID = "luisalbertor/botbingx"

def deploy():
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN environment variable is required for deployment.")

    logger.info("Initializing Hugging Face API client...")
    api = HfApi(token=HF_TOKEN)
    
    # 1. Ensure the Space repository exists on HF
    logger.info(f"Ensuring Hugging Face Space repository '{REPO_ID}' exists...")
    try:
        create_repo(
            repo_id=REPO_ID,
            token=HF_TOKEN,
            repo_type="space",
            space_sdk="static",
            private=False,
            exist_ok=True
        )
        logger.info(f"Repository '{REPO_ID}' validated successfully.")
    except Exception as e:
        logger.warning(f"Note on repository check/creation: {e}")
        
    # 2. Upload the local codebase to the Space
    current_dir = os.path.dirname(os.path.abspath(__file__))
    logger.info(f"Uploading files from '{current_dir}' to Space '{REPO_ID}'...")
    
    try:
        # Uploading everything except temporary/local database files and cache directories
        api.upload_folder(
            folder_path=current_dir,
            repo_id=REPO_ID,
            repo_type="space",
            ignore_patterns=[
                "__pycache__", 
                "*.pyc", 
                "*.bak",
                "*.db", 
                ".git", 
                ".gemini", 
                "brain", 
                "scratch",
                "*.log",
                "trading.db",
                "deploy.py"
            ]
        )
        logger.info("=" * 60)
        logger.info("DEPLOYMENT COMPLETED SUCCESSFULLY!")
        logger.info(f"Your Premium Algorithmic Trading Bot is now live at:")
        logger.info(f"https://huggingface.co/spaces/{REPO_ID}")
        logger.info("=" * 60)
        return True
    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        return False

if __name__ == "__main__":
    success = deploy()
    sys.exit(0 if success else 1)
