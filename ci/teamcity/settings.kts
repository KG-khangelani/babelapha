package _Self.buildTypes

import jetbrains.buildServer.configs.kotlin.*
import jetbrains.buildServer.configs.kotlin.buildFeatures.perfmon
import jetbrains.buildServer.configs.kotlin.buildSteps.Qodana
import jetbrains.buildServer.configs.kotlin.buildSteps.dockerCommand
import jetbrains.buildServer.configs.kotlin.buildSteps.qodana
import jetbrains.buildServer.configs.kotlin.triggers.vcs

object AirflowGitSync : BuildType({
    name = "Airflow GitSync"
    description = "automatically syncs DAGs from the Git repository to your Airflow deployment"

    params {
        param("env.GITHUB_TOKEN", "%system.github_token%")
        param("env.DAGS_FOLDER", "/opt/airflow/dags")
        param("env.AIRFLOW_NAMESPACE", "airflow")
        param("env.AIRFLOW_POD_LABEL", "component=scheduler")
        param("env.SOURCE_DIR", "pipelines/airflow/dags")
    }

    vcs {
        root(HttpsGithubComKgKhangelaniBabelaphaRefsHeadsMain3)
    }
    steps {
        qodana {
            name = "maqondana scan"
            id = "maqondana_scan"
            enabled = false
            linter = python {
                version = Qodana.PythonVersion.LATEST
            }
            inspectionProfile = default()
            additionalDockerArguments = "--memory=4g --memory-swap=4g"
            cli = "v2025.1.1"
            cloudToken = "******"
        }
        dockerCommand {
            name = "Build Validator Image"
            id = "Validate_DAG_Syntax_1"
            commandType = build {
                source = file {
                    path = "docker/airflow-gitsync/Dockerfile.validate"
                }
                namesAndTags = "airflow-dag-validator:%build.number%"
                commandArgs = "--pull"
            }
        }
        dockerCommand {
            name = "Validate DAG Syntax"
            id = "DockerCommand"
            commandType = other {
                subCommand = "run"
                commandArgs = """
                    --rm
                    -v %teamcity.build.checkoutDir%:/workspace
                    airflow-dag-validator:%build.number%
                """.trimIndent()
            }
        }
        dockerCommand {
            name = "Build GitSync Container"
            id = "Build_GitSync_Container"
            commandType = build {
                source = file {
                    path = "docker/airflow-gitsync/Dockerfile"
                }
                namesAndTags = """
                    airflow-gitsync:%build.number%
                    airflow-gitsync:latest
                """.trimIndent()
                commandArgs = "--pull"
            }
        }
        dockerCommand {
            name = "Test Network Connectivity"
            id = "Test_Network_Connectivity"
            enabled = false
            commandType = other {
                subCommand = "run"
                commandArgs = """
                    --rm
                                --network host
                                alpine:latest
                                ping -c 3 github.com
                """.trimIndent()
            }
        }
        dockerCommand {
            name = "Sync DAGs to Airflow"
            id = "Sync_DAGs_to_Airflow"
            commandType = other {
                subCommand = "run"
                commandArgs = """
                    --rm
                    -e WORKSPACE_DIR=/workspace
                    -e BUILD_NUMBER=%build.number%
                    -e BUILD_VCS_NUMBER=%build.vcs.number%
                    -e AIRFLOW_NAMESPACE=airflow
                    -e KUBERNETES_SERVICE_HOST=%env.KUBERNETES_SERVICE_HOST%
                    -e KUBERNETES_SERVICE_PORT=%env.KUBERNETES_SERVICE_PORT%
                    -v /etc/resolv.conf:/etc/resolv.conf:ro
                    -v %teamcity.build.checkoutDir%:/workspace:ro
                    -v /var/run/secrets/kubernetes.io/serviceaccount:/var/run/secrets/kubernetes.io/serviceaccount:ro
                    airflow-gitsync:%build.number%
                """.trimIndent()
            }
        }
    }
    triggers {
        vcs {
            triggerRules = """
                +:pipelines/airflow/dags/**
                +:docker/airflow-gitsync/**
            """.trimIndent()
            branchFilter = "+:refs/heads/main"
            perCheckinTriggering = true
            enableQueueOptimization = false
        }
    }

    features {
        perfmon {
        }
    }
})

object MediaPipelineDockerImages : BuildType({
    name = "Build Media Pipeline Docker Images"
    description = "Build and push ClamAV, Validate, and Transcode container images for media processing pipeline"

    vcs {
        root(HttpsGithubComKgKhangelaniBabelaphaRefsHeadsMain3)
    }

    steps {
        dockerCommand {
            name = "Build ClamAV Scanner Image"
            id = "Build_ClamAV_Image"
            commandType = build {
                source = file {
                    path = "docker/clamav/dockerfile"
                }
                namesAndTags = "clamav:%build.number%"
                commandArgs = "--pull"
            }
        }
        dockerCommand {
            name = "Build Validate Image"
            id = "Build_Validate_Image"
            commandType = build {
                source = file {
                    path = "docker/validate/dockerfile"
                }
                namesAndTags = "validate:%build.number%"
                commandArgs = "--pull"
            }
        }
        dockerCommand {
            name = "Build Transcode Image"
            id = "Build_Transcode_Image"
            commandType = build {
                source = file {
                    path = "docker/transcode/dockerfile"
                }
                namesAndTags = "transcode:%build.number%"
                commandArgs = "--pull"
            }
        }
        dockerCommand {
            name = "Make Images Available to Kubernetes"
            id = "Export_Images_For_K8s"
            commandType = other {
                subCommand = "tag"
                commandArgs = "clamav:%build.number% localhost/clamav:latest"
            }
        }
        dockerCommand {
            name = "Tag Validate for Local Registry"
            id = "Tag_Validate_Local"
            commandType = other {
                subCommand = "tag"
                commandArgs = "validate:%build.number% localhost/validate:latest"
            }
        }
        dockerCommand {
            name = "Tag Transcode for Local Registry"
            id = "Tag_Transcode_Local"
            commandType = other {
                subCommand = "tag"
                commandArgs = "transcode:%build.number% localhost/transcode:latest"
            }
        }
    }

    triggers {
        vcs {
            triggerRules = """
                +:docker/clamav/**
                +:docker/validate/**
                +:docker/transcode/**
                +:docker/utils/**
            """.trimIndent()
            branchFilter = "+:refs/heads/main"
            perCheckinTriggering = true
            enableQueueOptimization = false
        }
    }

    features {
        perfmon {
        }
    }
})

