# Bootstrap Guide — Agentic AI Solution on Azure

This guide walks you through setting up, running, and deploying the Agentic AI solution both locally and in Azure.

---

## 1. Prerequisites

Ensure the following tools are installed:

- **Azure CLI** (≥ 2.55.0) → [Install](https://learn.microsoft.com/cli/azure/install-azure-cli)
- **Azure Developer CLI (azd)** (≥ 1.6.0) → [Install](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- **Node.js** (≥ 18.x LTS) → [Install](https://nodejs.org/)
- **Python** (≥ 3.10) with `pip`
- **Git** (≥ 2.40)
- An **Azure subscription** with resource creation permissions

---

## 2. Clone the Repository

```bash
git clone https://github.com/your-org/agentic-ai-solution.git
cd agentic-ai-solution
```

## 3. Configure Environment Variables

Copy the sample environment file:

```bash
Copier le code
cp .env.sample .env
```
Edit .env and set your Azure resource details:

```env
AZURE_SUBSCRIPTION_ID=<your-subscription-id>
AZURE_OPENAI_ENDPOINT=https://<your-openai-resource>.openai.azure.com/
AZURE_OPENAI_KEY=<your-openai-key>
AZURE_SEARCH_ENDPOINT=https://<your-search-resource>.search.windows.net
AZURE_SEARCH_KEY=<your-search-key>
```
**Security Tip**: Never commit .env files to version control.

## 4. Install Dependencies
Backend (Python)

```bash
cd src/backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

Frontend (Node.js)

```bash
cd ../frontend
npm install
```

## 5. Run Locally
Backend:

```bash
cd src/backend
source .venv/bin/activate
python app.py
```

Frontend:

```bash
cd src/frontend
npm start
```

Access the app at:
http://localhost:3000

## 6. Deploy to Azure
Login and select subscription:

```bash
az login
az account set --subscription "<your-subscription-id>"
```

Deploy using Azure Developer CLI:

```bash
azd up
```

This will:

- Provision Azure resources (Container Apps, Azure OpenAI, Azure AI Search, Storage)
- Deploy backend and frontend
- Output the public app URL


## 7. Post-Deployment Tasks
- Test the AI agent in the deployed environment
- View logs:
```bash
az containerapp logs show --name <app-name> --resource-group <rg-name>
```
- Modify accelerator.yaml to change scenarios or tools
- Add custom data to Azure AI Search for richer responses

## 8. Cleanup Resources
To avoid charges:

```bash
azd down
```

## 9. Troubleshooting

- **Authentication errors** → Ensure az login was successful and subscription is set
- **Port conflicts locally** → Change frontend port in package.json
- **Missing dependencies** → Run pip install -r requirements.txt or npm install again
**Next Steps**:

- Customize prompts and tools in src/scenarios/<scenario-id>/
- Integrate external APIs for advanced agent capabilities
- Add CI/CD workflows for automated deployments

---

This version adds:
- **Security best practices** (don’t commit `.env`)
- **Troubleshooting section**
- **Clearer step-by-step formatting**
- **Explicit upgrade commands** for dependencies

---

If you want, I can now **extend this with a matching `accelerator.yaml`** so you have a **fully runnable Azure Agentic AI starter kit**.  
Would you like me to prepare that next?