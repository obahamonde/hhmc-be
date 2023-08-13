import base64
import json
import time
from typing import List, Optional

import boto3
import click
import docker
from aiofauna import BaseModel, Field, setup_logging
from dotenv import load_dotenv

load_dotenv()

logger = setup_logging(__name__)

ecr = boto3.client("ecr")

ecs = boto3.client("ecs")

ec2 = boto3.client("ec2")


class NetworkConfiguration(BaseModel):
    vpc_id: str = Field(default="vpc-0847a043b578b3b60", description="VPC ID")
    subnets: List[str] = Field(default_factory=list, description="Subnets to deploy to")
    security_groups: List[str] = Field(
        default_factory=list, description="Security groups to deploy to"
    )


# Create a boto3 client for ECS
ecs_client = boto3.client("ecs")


def is_service_ready(cluster_arn, service_name):
    client = boto3.client("ecs")
    try:
        response = client.describe_services(
            cluster=cluster_arn, services=[service_name]
        )
        if response["services"]:
            service = response["services"][0]

            # Check if the desired count equals the running count and if the status is 'ACTIVE'
            return (
                service.get("desiredCount") == service.get("runningCount")
                and service.get("status") == "ACTIVE"
            )
        else:
            print(
                f"No services found with the name {service_name} in cluster {cluster_arn}"
            )
            return False
    except Exception as e:
        print(f"An error occurred while checking the service status: {e}")
        return False


def get_subnets_and_sgs(vpc_id: str = "vpc-0847a043b578b3b60") -> NetworkConfiguration:
    """
    Get subnets and security groups for a given VPC
    """

    ec2_client = boto3.client("ec2")
    response = ec2_client.describe_subnets(
        Filters=[
            {
                "Name": "vpc-id",
                "Values": [vpc_id],
            },
        ],
    )
    subnets = [subnet["SubnetId"] for subnet in response["Subnets"]]

    response = ec2_client.describe_security_groups(
        Filters=[
            {
                "Name": "vpc-id",
                "Values": [vpc_id],
            },
        ],
    )
    security_groups = [sg["GroupId"] for sg in response["SecurityGroups"]]
    return NetworkConfiguration(
        vpc_id=vpc_id,
        subnets=subnets,
        security_groups=security_groups,
    )


def get_service_ip(cluster_arn, service_name):
    ecs_client = boto3.client("ecs")
    ec2_client = boto3.client("ec2")

    # Describe the service to get the task ARNs
    service_response = ecs_client.describe_services(
        cluster=cluster_arn, services=[service_name]
    )
    task_arns = service_response["services"][0]["tasks"]

    # Describe the tasks to get the ENI ID
    task_response = ecs_client.describe_tasks(cluster=cluster_arn, tasks=task_arns)
    eni_id = task_response["tasks"][0]["attachments"][0]["details"][0]["value"]

    # Describe the ENIs to get the public IP address
    eni_response = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    public_ip = eni_response["NetworkInterfaces"][0]["Association"]["PublicIp"]

    return public_ip


def docker_login() -> docker.DockerClient:
    """
    Logs into docker and returns a docker client
    """
    response = ecr.get_authorization_token()
    username, password = (
        base64.b64decode(response["authorizationData"][0]["authorizationToken"])
        .decode()
        .split(":")
    )
    registry = response["authorizationData"][0]["proxyEndpoint"]
    docker_client = docker.from_env()
    login_response = docker_client.login(
        username=username, password=password, registry=registry
    )
    logger.info(login_response)
    return docker_client


def register_task_definition(image, tag):
    response = ecs.register_task_definition(
        family="my-task-family",
        containerDefinitions=[
            {
                "name": f"{image}-{tag}",
                "image": f"{image}:{tag}",
                "memory": 512,
                "cpu": 256,
                "essential": True,
            },
        ],
        requiresCompatibilities=["FARGATE"],
        cpu="256",
        memory="512",
        networkMode="awsvpc",  # Required for Fargate
    )
    logger.info(response)
    return response["taskDefinition"]["taskDefinitionArn"]


def deploy_service(cluster_name, task_definition_arn, desired_count=1):
    service_name = "my-service"
    network_configuration = get_subnets_and_sgs()

    try:
        response = ecs.describe_services(cluster=cluster_name, services=[service_name])

        if len(response["services"]) > 0:
            logger.info(f"Service {service_name} already exists, updating...")
            response = ecs.update_service(
                cluster=cluster_name,
                service=service_name,
                desiredCount=desired_count,
                taskDefinition=task_definition_arn,
            )
            logger.info(response)

    except Exception:
        logger.info(f"Service {service_name} does not exist, creating...")
        response = ecs.create_service(
            cluster=cluster_name,
            serviceName=service_name,
            taskDefinition=task_definition_arn,
            desiredCount=desired_count,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": network_configuration.subnets,
                    "securityGroups": network_configuration.security_groups,
                    "assignPublicIp": "ENABLED",
                }
            },
        )
        logger.info(response)

    arn = response["service"]["serviceArn"]

    # Wait until service is ready

    waiter = ecs.get_waiter("services_stable")

    waiter.wait(
        cluster=cluster_name,
        services=[service_name],
    )

    logger.info(f"Service {service_name} is ready")

    service_ready = False

    while not service_ready:
        service_ready = is_service_ready(cluster_name, service_name)
        logger.info(f"Service {service_name} is not ready, Polling...")
        time.sleep(3)

    logger.info(f"Service {service_name} is running")

    ip_ = None

    while not ip_:
        try:
            ip_ = get_service_ip(cluster_name, service_name)
            if ip_:
                break
            else:
                logger.info(f"Service {service_name} is not ready, Polling...")
                time.sleep(3)
        except Exception:
            logger.info(f"Service {service_name} is not ready, Polling...")
            time.sleep(3)

    logger.info(f"Service {service_name} is running at {ip_}")

    return {
        "service_name": service_name,
        "service_arn": arn,
        "ip": ip_,
    }


class Deployments(BaseModel):
    """
    A model for deployments
    """

    image: Optional[str] = Field(default=None, description="Docker image to deploy")
    tag: Optional[str] = Field(default=None, description="Docker tag to deploy")
    uri: Optional[str] = Field(default=None, description="Docker URI to deploy")
    cluster: Optional[str] = Field(
        default=None, description="Fauna cluster to deploy to"
    )

    def build(self, image: str, tag: str):
        """
        Builds a docker image and returns the image and tag
        """
        docker_client = docker_login()
        image, logs = docker_client.images.build(path=".", tag=f"{image}:{tag}")  # type: ignore
        for line in logs:
            logger.info(line)
        logger.info("Built image %s:%s", image, tag)
        self.image = image
        self.tag = tag
        return self

    def push(self, image: str, tag: str):
        """
        Pushes a docker image to ECR and returns the URI
        """
        res = ecr.describe_repositories(repositoryNames=[image])
        repository = res["repositories"][0]
        logger.info(res)
        docker_client = docker_login()
        image = docker_client.images.get(image)  # type: ignore
        image.tag(tag=tag, repository=repository["repositoryUri"])  # type: ignore
        res = docker_client.images.push(
            tag=tag, repository=repository["repositoryUri"], stream=True
        )
        for line in res:
            logger.info(json.loads(line.decode("utf-8")))
        self.uri = repository["repositoryUri"]
        logger.info("Pushed image %s:%s to %s", image, tag, repository["repositoryUri"])
        return self

    def deploy(self, uri: str, cluster: str = "aiofauna"):
        """
        Deploys a docker image to a Fauna cluster
        """
        logger.info("Deploying %s to %s", uri, cluster)
        task_definition_arn = register_task_definition(uri, self.tag)
        deploy_service(cluster, task_definition_arn)


deployment = Deployments()


@click.group()
def cli():
    pass


@cli.command()
@click.option("--image", default="hhmc", help="Docker image to build")
@click.option("--tag", default="latest", help="Docker tag to build")
def build(image, tag):
    deployment.build(image, tag)


@cli.command()
@click.option("--image", default="hhmc", help="Docker image to push")
@click.option("--tag", default="latest", help="Docker tag to push")
def push(image, tag):
    deployment.push(image, tag)


@cli.command()
@click.option("--uri", default="hhmc", help="Docker URI to deploy")
@click.option("--cluster", default="aiofauna", help="Fauna cluster to deploy to")
def deploy(uri, cluster):
    deployment.deploy(uri, cluster)


if __name__ == "__main__":
    cli()
