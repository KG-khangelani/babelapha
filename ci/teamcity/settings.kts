import jetbrains.buildServer.configs.kotlin.v2019_2.Project
import jetbrains.buildServer.configs.kotlin.v2019_2.buildSteps.script
import jetbrains.buildServer.configs.kotlin.v2019_2.triggers.vcs
import jetbrains.buildServer.configs.kotlin.v2019_2.version
import jetbrains.buildServer.configs.kotlin.v2019_2.DslContext
import jetbrains.buildServer.configs.kotlin.v2019_2.BuildType
import jetbrains.buildServer.configs.kotlin.v2019_2.buildSteps
import jetbrains.buildServer.configs.kotlin.v2019_2.triggers
import jetbrains.buildServer.configs.kotlin.v2019_2.buildSteps.dockerCommand

version = "2024.03"

project {
    id("Babelapha")
    name = "Babelapha"
    description = "Continuous integration pipelines for the media platform project."

    buildType(MediaPipelineChecks)
    buildType(BuildClamAVImage)
    buildType(BuildValidateImage)
    buildType(BuildTranscodeImage)
}

object MediaPipelineChecks : BuildType({
    name = "Media Pipeline Checks"
    description = "Validate Airflow DAGs, Pachyderm specs, and run unit placeholders."

    vcs {
        root(DslContext.settingsRoot)
    }

    steps {
        script {
            name = "Validate Airflow DAG syntax"
            scriptContent = """
            python -m venv .venv
            . .venv/bin/activate
            pip install "apache-airflow"
            python -m compileall pipelines/airflow/dags
            """.trimIndent()
        }

        script {
            name = "Lint Pachyderm pipeline YAML"
            scriptContent = """
            python -m venv .venv-yq
            . .venv-yq/bin/activate
            pip install yq
            yq eval '.' pipelines/pachyderm/transcription-pipeline.yaml >/dev/null
            """.trimIndent()
        }

        script {
            name = "Placeholder tests"
            scriptContent = """
            echo "TODO: add unit/integration tests"
            """.trimIndent()
        }
    }

    triggers {
        vcs {
            branchFilter = "+:refs/heads/*"
        }
    }
})

object BuildClamAVImage : BuildType({
    name = "Build ClamAV Image"
    description = "Build Docker image for virus scanning"

    vcs {
        root(DslContext.settingsRoot)
    }

    requirements {
        contains("docker.server.osType", "linux")
    }

    steps {
        script {
            name = "Copy utility files"
            scriptContent = """
            cp docker/utils/pfs_move.py docker/clamav/
            """.trimIndent()
        }

        dockerCommand {
            name = "Build and import to containerd"
            commandType = other {
                subCommand = "build"
                commandArgs = """
                -t clamav:%build.number%
                -t clamav:latest
                -f docker/clamav/dockerfile
                docker/clamav
                """.trimIndent()
            }
        }

        script {
            name = "Load into containerd on all nodes"
            scriptContent = """
            # Save image to tar
            docker save clamav:%build.number% -o /tmp/clamav.tar
            
            # Import to local containerd
            ctr -n k8s.io images import /tmp/clamav.tar
            
            # Copy to other nodes and import
            for node in 192.168.10.12 192.168.10.13 192.168.10.10; do
                echo "Loading image on node ${'$'}node"
                scp /tmp/clamav.tar ${'$'}node:/tmp/ || true
                ssh ${'$'}node "ctr -n k8s.io images import /tmp/clamav.tar && rm /tmp/clamav.tar" || true
            done
            
            # Cleanup
            rm /tmp/clamav.tar
            """.trimIndent()
        }
    }

    triggers {
        vcs {
            branchFilter = "+:refs/heads/*"
            triggerRules = "+:docker/clamav/**"
        }
    }
})

object BuildValidateImage : BuildType({
    name = "Build Validate Image"
    description = "Build Docker image for media validation"

    vcs {
        root(DslContext.settingsRoot)
    }

    requirements {
        contains("docker.server.osType", "linux")
    }

    steps {
        script {
            name = "Copy utility files"
            scriptContent = """
            cp docker/utils/pfs_move.py docker/validate/
            """.trimIndent()
        }

        dockerCommand {
            name = "Build image"
            commandType = other {
                subCommand = "build"
                commandArgs = """
                -t validate:%build.number%
                -t validate:latest
                -f docker/validate/dockerfile
                docker/validate
                """.trimIndent()
            }
        }

        script {
            name = "Load into containerd on all nodes"
            scriptContent = """
            # Save image to tar
            docker save validate:%build.number% -o /tmp/validate.tar
            
            # Import to local containerd
            ctr -n k8s.io images import /tmp/validate.tar
            
            # Copy to other nodes and import
            for node in 192.168.10.12 192.168.10.13 192.168.10.10; do
                echo "Loading image on node ${'$'}node"
                scp /tmp/validate.tar ${'$'}node:/tmp/ || true
                ssh ${'$'}node "ctr -n k8s.io images import /tmp/validate.tar && rm /tmp/validate.tar" || true
            done
            
            # Cleanup
            rm /tmp/validate.tar
            """.trimIndent()
        }
    }

    triggers {
        vcs {
            branchFilter = "+:refs/heads/*"
            triggerRules = "+:docker/validate/**"
        }
    }
})

object BuildTranscodeImage : BuildType({
    name = "Build Transcode Image"
    description = "Build Docker image for media transcoding"

    vcs {
        root(DslContext.settingsRoot)
    }

    requirements {
        contains("docker.server.osType", "linux")
    }

    steps {
        dockerCommand {
            name = "Build image"
            commandType = other {
                subCommand = "build"
                commandArgs = """
                -t transcode:%build.number%
                -t transcode:latest
                -f docker/transcode/dockerfile
                docker/transcode
                """.trimIndent()
            }
        }

        script {
            name = "Load into containerd on all nodes"
            scriptContent = """
            # Save image to tar
            docker save transcode:%build.number% -o /tmp/transcode.tar
            
            # Import to local containerd
            ctr -n k8s.io images import /tmp/transcode.tar
            
            # Copy to other nodes and import
            for node in 192.168.10.12 192.168.10.13 192.168.10.10; do
                echo "Loading image on node ${'$'}node"
                scp /tmp/transcode.tar ${'$'}node:/tmp/ || true
                ssh ${'$'}node "ctr -n k8s.io images import /tmp/transcode.tar && rm /tmp/transcode.tar" || true
            done
            
            # Cleanup
            rm /tmp/transcode.tar
            """.trimIndent()
        }
    }

    triggers {
        vcs {
            branchFilter = "+:refs/heads/*"
            triggerRules = "+:docker/transcode/**"
        }
    }
})
