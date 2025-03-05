# Initiate by running this command: python -m uvicorn app.web_app:app --reload

# Ask a question about the knowledge base:
# http://127.0.0.1:8000/bedrock/query?text=who%20is%20madonna

# Ask a general question:
# http://127.0.0.1:8000/bedrock/invoke?text=who%20is%20madonna

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import boto3
import os
import json
from dotenv import load_dotenv
import logging
from botocore.exceptions import BotoCoreError, ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file (for local development)
# Elastic Beanstalk will use environment variables configured in the console
load_dotenv()

# Retrieve AWS configuration from environment variables
AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
MODEL_ID = os.getenv("MODEL_ID")  # Make sure this is added in EB console
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID")
MODEL_ARN = os.getenv("MODEL_ARN")

# Log environment variables for debugging (excluding sensitive data)
logger.info(f"AWS_REGION: {AWS_REGION}")
logger.info(f"MODEL_ID configured: {'Yes' if MODEL_ID else 'No'}")
logger.info(f"KNOWLEDGE_BASE_ID configured: {'Yes' if KNOWLEDGE_BASE_ID else 'No'}")
logger.info(f"MODEL_ARN configured: {'Yes' if MODEL_ARN else 'No'}")

# Create FastAPI app
app = FastAPI()

# Add a health check endpoint for Elastic Beanstalk
@app.get("/health")
async def health():
    return {"status": "healthy"}

# Serve static files
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
    logger.info("Static files mounted successfully")
except Exception as e:
    logger.error(f"Failed to mount static files: {e}")

# Set up Jinja2 templates
try:
    templates = Jinja2Templates(directory="templates")
    logger.info("Templates directory configured successfully")
except Exception as e:
    logger.error(f"Failed to configure templates: {e}")

@app.get("/")
async def home(request: Request):
    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception as e:
        logger.error(f"Error rendering home page: {e}")
        return {"error": "Error rendering home page", "details": str(e)}

# Initialize AWS clients using IAM role
try:
    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    bedrock_agent_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
    logger.info("AWS clients initialized successfully")
except (BotoCoreError, ClientError) as e:
    logger.error(f"Failed to initialize AWS clients: {e}")
    # Don't raise the exception here to allow the application to start

@app.get("/bedrock/invoke")
async def invoke_model(text: str = Query(..., description="Input text for the model")):
    """
    Endpoint for invoking the model.
    """
    if not MODEL_ID:
        logger.error("MODEL_ID environment variable is missing")
        raise HTTPException(status_code=500, detail="MODEL_ID is not configured.")
    
    try:
        # Format the prompt according to Llama 3's requirements
        formatted_prompt = f"""
        <|begin_of_text|><|start_header_id|>user<|end_header_id|>
        {text}
        <|eot_id|>
        <|start_header_id|>assistant<|end_header_id|>
        """

        # Construct the request payload
        request_payload = {
            "prompt": formatted_prompt,
            "max_gen_len": 512,
            "temperature": 0.5
        }

        # Invoke the model
        response = bedrock_client.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_payload)
        )

        # Read and parse the response body
        response_body = json.loads(response['body'].read().decode('utf-8'))

        # Extract the generated text
        generated_text = response_body.get("generation", "")

        if not generated_text:
            logger.error("Model did not return any content.")
            raise HTTPException(status_code=500, detail="Model did not return any content.")
        
        return {"response": generated_text}
    except ClientError as e:
        logger.error(f"AWS ClientError: {e}")
        raise HTTPException(status_code=500, detail=f"AWS Client error: {str(e)}")
    except BotoCoreError as e:
        logger.error(f"AWS BotoCoreError: {e}")
        raise HTTPException(status_code=500, detail=f"AWS BotoCore error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@app.get("/bedrock/query")
async def query_with_knowledge_base(text: str = Query(..., description="Input text for the model")):
    """
    Endpoint for model invocation with knowledge base retrieval and generation.
    """
    if not KNOWLEDGE_BASE_ID or not MODEL_ARN:
        logger.error("Knowledge base configuration is missing")
        raise HTTPException(status_code=500, detail="Knowledge base configuration is missing.")
    
    try:
        response = bedrock_agent_client.retrieve_and_generate(
            input={"text": text},
            retrieveAndGenerateConfiguration={
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": KNOWLEDGE_BASE_ID,
                    "modelArn": MODEL_ARN
                },
                "type": "KNOWLEDGE_BASE"
            }
        )
        return {"response": response["output"]["text"]}
    except ClientError as e:
        logger.error(f"AWS ClientError: {e}")
        raise HTTPException(status_code=500, detail=f"AWS Client error: {str(e)}")
    except BotoCoreError as e:
        logger.error(f"AWS BotoCoreError: {e}")
        raise HTTPException(status_code=500, detail=f"AWS BotoCore error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
