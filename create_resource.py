import os
import json
import time
import random
import string
import requests
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from azure.cosmos import CosmosClient, PartitionKey
from azure.mgmt.cosmosdb import CosmosDBManagementClient
from azure.mgmt.cosmosdb.models import DatabaseAccountCreateUpdateParameters, Location, Capability
from azure.containerregistry import ContainerRegistryClient
from azure.mgmt.containerregistry import ContainerRegistryManagementClient
from azure.mgmt.containerregistry.models import Registry
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.search import SearchManagementClient
from azure.mgmt.search.models import SearchService, Sku
from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.storage.models import StorageAccountCreateParameters, Sku, Kind, AccessTier
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.web.models import Site, SiteConfig, SkuDescription, HostingEnvironmentProfile, AppServicePlan, NameValuePair
from azure.mgmt.resource.resources.models import Deployment

    
subscription_id = "c1fa0f8f-3890-4273-b556-2d11036fbdf4"

def create_cosmos_db_resource(resource_group_name, cosmos_db_account_name, location="eastus"):
    location = "eastus"

    credential = DefaultAzureCredential()
    resource_client = ResourceManagementClient(credential, subscription_id)
    client = CosmosDBManagementClient(credential, subscription_id)

    database_account_create_update_parameters = DatabaseAccountCreateUpdateParameters(
        location=location,
        locations=[Location(location_name=location)],
        kind="GlobalDocumentDB",
        consistency_policy={
            "defaultConsistencyLevel": "Session",
            "maxIntervalInSeconds": 5,
            "maxStalenessPrefix": 100
        },
        capabilities=[Capability(name="EnableSql")]
    )

    poller = client.database_accounts.begin_create_or_update(
        resource_group_name,
        cosmos_db_account_name,
        database_account_create_update_parameters
    )
    poller.result()
    resources = resource_client.resources.list_by_resource_group(resource_group_name)
    cosmosdb_client = CosmosDBManagementClient(credential, subscription_id)

    for resource in resources:
        if resource.type == 'Microsoft.DocumentDB/databaseAccounts':
            cosmos_db_account = cosmosdb_client.database_accounts.get(resource_group_name, cosmos_db_account_name)
            cosmos_db_endpoint = cosmos_db_account.document_endpoint
            cosmos_db_keys = cosmosdb_client.database_accounts.list_keys(resource_group_name, resource.name)
            cosmos_db_key = cosmos_db_keys.primary_master_key
            client = CosmosClient(cosmos_db_endpoint, cosmos_db_key)
            print(cosmos_db_key, cosmos_db_endpoint)
            database_name = "DATABASE"
            database = client.create_database_if_not_exists(id=database_name)
            container_names = ["client_credential", "Users_Container", "confirmation_code", "DataBaseContainer"]
            for container_name in container_names:
                container = database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/id")
                )
    print("criou")
    return True

def create_cognive_search_resource(resource_group_name, search_service_name, data_list):
    sku = "standard" 
    credential = DefaultAzureCredential()

    client = SearchManagementClient(credential, subscription_id)
    resource_client = ResourceManagementClient(credential, subscription_id)
    resources = resource_client.resources.list_by_resource_group(resource_group_name)

    search_service_params = SearchService(
        location="eastus",
        sku=Sku(name=sku)
    )

    poller = client.services.begin_create_or_update(resource_group_name, search_service_name, search_service_params)
    poller.result()
    for resource in resources:
        if resource.type == 'Microsoft.Search/searchServices': 
            search_client = SearchManagementClient(credential, subscription_id)
            search_service = search_client.services.get(resource_group_name, resource.name)
            keys = search_client.admin_keys.get(resource_group_name, resource.name)
            keys = keys.primary_key
            search_endpoint = f"https://{search_service.name}.search.windows.net/"
            index_name = "azureblob-index"
            storage_account_name = "rsgdevmdhealthbd40"
            storage_account_key = "FEB0ZZaub76OPnCFfvsl1vpD1jarrgwREToaF7ENqcAc6cCzoXpOK64jHB9bhRzTcFR4hlb/NHT++AStlUjQNw=="
            container_name = "database-mdhealth"
            search_api_version = "2020-06-30"
            search_api_key = keys
            
            index_url = f"{search_endpoint}indexes/{index_name}?api-version={search_api_version}"
            documents_url = f"{search_endpoint}indexes/{index_name}/docs/index?api-version={search_api_version}"

            search_headers = {
                "Content-Type": "application/json",
                "api-key": search_api_key
            }

            index_definition = {
                "name": index_name,
                "fields": [
                    {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
                    {"name": "content", "type": "Edm.String", "searchable": True},
                    {"name": "metadata_storage_path", "type": "Edm.String"},
                    {"name": "metadata_storage_name", "type": "Edm.String"},
                ]
            }
            response = requests.put(index_url, headers=search_headers, json=index_definition)
            if response.status_code == 201:
                for url in data_list:
                    try:
                        add_file_to_azure_cognitive_search(url, search_endpoint, index_name, search_api_key)
                    except: None
                search_api_version = "2020-06-30"
                storage_connection_string = f"DefaultEndpointsProtocol=https;AccountName={storage_account_name};AccountKey={storage_account_key};EndpointSuffix=core.windows.net"
                indexer_parameters = {
                    "name": 'azureblob-indexer',
                    "dataSourceName": "blob-datasource",
                    "targetIndexName": index_name,
                    "parameters": {
                        "maxFailedItems": 10,
                        "maxFailedItemsPerBatch": 5
                    },
                    "schedule": {
                        "interval": "PT1H"
                    }
                }
                data_source_connection = {
                    "name": "blob-datasource",
                    "type": "azureblob",
                    "credentials": {
                        "connectionString": storage_connection_string
                    },
                    "container": {
                        "name": container_name
                    },
                    "dataChangeDetectionPolicy": {
                        "@odata.type": "#Microsoft.Azure.Search.HighWaterMarkChangeDetectionPolicy",
                        "highWaterMarkColumnName": "metadata_storage_last_modified"
                    }
                }
                
                headers = {
                    "Content-Type": "application/json",
                    "api-key": search_api_key
                }
                data_source_url = f"{search_endpoint}datasources/blob-datasource?api-version={search_api_version}"
                response = requests.put(data_source_url, headers=headers, json=data_source_connection)
                if response.status_code != 201:
                    return False

                indexer_url = f"{search_endpoint}indexers/azureblob-indexer?api-version={search_api_version}"
                response = requests.put(indexer_url, headers=headers, json=indexer_parameters)
                if response.status_code != 201:
                    return False
                return True
            else:
                return False

def create_blob_storage(resource_group_name, blob_storage_name):
    storage_account_name = blob_storage_name[:21] 
    location = "eastus"
    sku = "Standard_LRS"

    credential = DefaultAzureCredential()

    storage_client = StorageManagementClient(credential, subscription_id)

    storage_account_params = StorageAccountCreateParameters(
        sku=Sku(name=sku),
        kind=Kind.storage_v2, 
        location=location,
        access_tier=AccessTier.hot 
    )

    poller = storage_client.storage_accounts.begin_create(resource_group_name, storage_account_name, storage_account_params)
    poller.result()
    blob_service_client = BlobServiceClient(account_url=f"https://{storage_account_name}.blob.core.windows.net/", credential=credential)

    try:
        container_client = blob_service_client.create_container("message-history")
    except:
        return True

    return True

def create_container_registry(resource_group_name, container_registry):
    credential = DefaultAzureCredential()
    client = ContainerRegistryManagementClient(credential, subscription_id)
    
    registry_params = Registry(
        location="eastus",
        sku=Sku(name='Standard'),
        admin_user_enabled=True  
    )

    poller = client.registries.begin_create(resource_group_name, container_registry, registry_params)
    poller.result()
    
    return True

def update_webapp_with_environment_back(resource_group_name, webapp_name, container_name, key):
    credential = DefaultAzureCredential()

    variables = [
        {"name": "DOCKER_REGISTRY_SERVER_USERNAME", "value": container_name},
        {"name": "DOCKER_REGISTRY_SERVER_PASSWORD", "value": key},
        {"name": "DOCKER_REGISTRY_SERVER_URL", "value": f"https://{container_name}.azurecr.io"},
        {"name": "WEBSITES_ENABLE_APP_SERVICE_STORAGE", "value": "false"},
        {"name": "WEBSITES_PORT", "value": "8000"}
    ]

    web_client = WebSiteManagementClient(credential, subscription_id)

    site_config = SiteConfig(app_settings=[NameValuePair(name=var["name"], value=var["value"]) for var in variables])

    web_client.web_apps.begin_create_or_update(resource_group_name, webapp_name, Site(location='eastus', site_config=site_config))
    
def update_webapp_with_environment_front(resource_group_name, webapp_name, container_name, key):
    credential = DefaultAzureCredential()

    variables = [
        {"name": "DOCKER_REGISTRY_SERVER_USERNAME", "value": container_name},
        {"name": "DOCKER_REGISTRY_SERVER_PASSWORD", "value": key},
        {"name": "DOCKER_REGISTRY_SERVER_URL", "value": f"https://{container_name}.azurecr.io"},
        {"name": "WEBSITES_ENABLE_APP_SERVICE_STORAGE", "value": "false"},
        {"name": "WEBSITES_PORT", "value": "3000"},
        {"name": "WEBSITES_CONTAINER_START_TIME_LIMIT", "value": "1800"}
        
    ]

    web_client = WebSiteManagementClient(credential, subscription_id)

    site_config = SiteConfig(app_settings=[NameValuePair(name=var["name"], value=var["value"]) for var in variables])

    web_client.web_apps.begin_create_or_update(resource_group_name, webapp_name, Site(location='eastus', site_config=site_config))

def create_function_app(resource_group_name, function_app_name, container_registry, container_image_name):
    credential = DefaultAzureCredential()
    web_client = WebSiteManagementClient(credential, subscription_id)
    
    DOCKER_REGISTRY_SERVER_USERNAME = container_registry
    DOCKER_REGISTRY_SERVER_PASSWORD = "1WkZ/QjM96ujCNDQ/IwT5TctJu+zfX655yaxbHcCjl+ACRA+cXFE"
    DOCKER_REGISTRY_SERVER_URL = f"https://{container_registry}.azurecr.io"
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "false"
    WEBSITES_PORT = "8000"
    DOCKER_CUSTOM_IMAGE_NAME = f"{container_registry}.azurecr.io/{container_image_name}:v1"

    site_config = SiteConfig(
        app_settings=[
            {"name": "WEBSITES_ENABLE_APP_SERVICE_STORAGE", "value": WEBSITES_ENABLE_APP_SERVICE_STORAGE},
            {"name": "WEBSITES_PORT", "value": WEBSITES_PORT},
            {"name": "DOCKER_REGISTRY_SERVER_USERNAME", "value": DOCKER_REGISTRY_SERVER_USERNAME},
            {"name": "DOCKER_REGISTRY_SERVER_PASSWORD", "value": DOCKER_REGISTRY_SERVER_PASSWORD},
            {"name": "DOCKER_REGISTRY_SERVER_URL", "value": DOCKER_REGISTRY_SERVER_URL},
            {"name": "DOCKER_CUSTOM_IMAGE_NAME", "value": DOCKER_CUSTOM_IMAGE_NAME},
            {"name": "DOCKER_ENABLE_CI", "value": "true"},  # Habilitar integração contínua do Docker
            {"name": "DOCKER_CI_BRANCH", "value": "main"},    # Ramo a ser monitorado para integração contínua do Docker
            {"name": "DOCKER_COMPOSE_ENABLED", "value": "false"}  # Desativar o uso de Compose
        ],
        linux_fx_version=f"DOCKER|{DOCKER_CUSTOM_IMAGE_NAME}"
    )

    plan = AppServicePlan(
        location="eastus",  
        sku=SkuDescription(
            name="B3", 
            tier="Basic"
        )
    )
    web_client.app_service_plans.begin_create_or_update(resource_group_name, function_app_name + '-plan', plan)

    create_site = web_client.web_apps.begin_create_or_update(
        resource_group_name=resource_group_name,
        name=function_app_name,
        site_envelope=Site(
            location="eastus",
            kind="linux",
            site_config=site_config,
            reserved=True
        )
    )

    print(create_site.result().as_dict())

# create_function_app("RSG_DEV_MDHealth", 't24-tesst', 'mdhealthcontainerdev', 'back-mdhealth-image-dev')
