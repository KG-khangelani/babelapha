import jetbrains.buildServer.configs.kotlin.v2019_2.Project
import jetbrains.buildServer.configs.kotlin.v2019_2.buildSteps.script
import jetbrains.buildServer.configs.kotlin.v2019_2.triggers.vcs
import jetbrains.buildServer.configs.kotlin.v2019_2.version
import jetbrains.buildServer.configs.kotlin.v2019_2.DslContext
import jetbrains.buildServer.configs.kotlin.v2019_2.BuildType
import jetbrains.buildServer.configs.kotlin.v2019_2.buildSteps
import jetbrains.buildServer.configs.kotlin.v2019_2.triggers

version = "2024.03"

project {
    id("Babelapha")
    name = "Babelapha"
    description = "Continuous integration pipelines for the media platform project."

    buildType(MediaPipelineChecks)
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
