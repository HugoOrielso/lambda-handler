# SpaceX Launches — Guía de Despliegue

## Tabla de Contenidos

1. [Prerrequisitos](#prerrequisitos)
2. [Configuración inicial de AWS](#configuración-inicial-de-aws)
3. [Despliegue de infraestructura con CloudFormation](#despliegue-de-infraestructura-con-cloudformation)
4. [Despliegue de la función Lambda](#despliegue-de-la-función-lambda)
5. [Despliegue del backend en ECS Fargate](#despliegue-del-backend-en-ecs-fargate)
6. [Verificación del sistema](#verificación-del-sistema)
7. [Arquitectura de componentes](#arquitectura-de-componentes)
8. [URLs públicas](#urls-públicas)

---

## Prerrequisitos

Antes de comenzar, asegúrate de tener instalado y configurado lo siguiente:

- **AWS CLI** v2 o superior — [Instalar](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html)
- **Docker** — [Instalar](https://docs.docker.com/get-docker/)
- **Git**
- **Node.js** 18+
- **Python** 3.11+
- Una cuenta de **AWS** con permisos de administrador
- Una cuenta de **GitHub** con acceso al repositorio

---

## Configuración inicial de AWS

### 1. Crear usuario IAM para CI/CD

Ve a **IAM → Users → Create user** y crea un usuario con las siguientes políticas:

- `AmazonECS_FullAccess`
- `AmazonEC2ContainerRegistryFullAccess`
- `AWSLambda_FullAccess`
- `AmazonDynamoDBFullAccess`
- `SecretsManagerReadWrite`
- `AWSCloudFormationFullAccess`
- `IAMFullAccess`

Genera las **Access Keys** y guárdalas — las necesitarás para GitHub Actions.

### 2. Configurar AWS CLI localmente

```bash
aws configure
# AWS Access Key ID: <tu-access-key>
# AWS Secret Access Key: <tu-secret-key>
# Default region name: us-east-2
# Default output format: json
```

### 3. Crear repositorio en Amazon ECR

```bash
aws ecr create-repository \
  --repository-name spacex-backend \
  --region us-east-2
```

Guarda la URL del repositorio — tendrá el formato:
```
<account-id>.dkr.ecr.us-east-2.amazonaws.com/spacex-backend
```

---

## Despliegue de infraestructura con CloudFormation

El archivo `infrastructure.yml` crea todos los recursos base:

- Tabla **DynamoDB** (`spaces_launches_spacex-infra`) — nombre fijo, no cambia entre deploys
- **Lambda** placeholder (`spacex-launches-handler`)
- **EventBridge Rule** (ejecución cada 6 horas)
- **IAM Roles** para Lambda y ECS (con permisos de DynamoDB incluidos)

> ⚠️ **IMPORTANTE:** El secreto `spacex-backend-secrets` se gestiona **manualmente fuera de CloudFormation** para evitar que se recree con sufijos aleatorios en cada deploy. Sigue el orden exacto de los pasos a continuación.

### Paso 1: Crear el secreto manualmente (solo la primera vez)

```bash
aws secretsmanager create-secret \
  --name spacex-backend-secrets \
  --secret-string '{"TABLE_NAME":"spaces_launches_spacex-infra","PORT":"4000"}' \
  --region us-east-2
```

> Si el secreto ya existe, actualízalo:
> ```bash
> aws secretsmanager update-secret \
>   --secret-id spacex-backend-secrets \
>   --secret-string '{"TABLE_NAME":"spaces_launches_spacex-infra","PORT":"4000"}' \
>   --region us-east-2
> ```

### Paso 2: Validar el template

```bash
aws cloudformation validate-template \
  --template-body file://infrastructure.yml \
  --region us-east-2
```

### Paso 3: Desplegar el stack

```bash
aws cloudformation deploy \
  --template-file infrastructure.yml \
  --stack-name spacex-infra \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Environment=prod \
  --region us-east-2
```

El proceso tarda aproximadamente 3-5 minutos. Al finalizar verás:

```
Successfully created/updated stack - spacex-infra
```

### Paso 4: Verificar los outputs

```bash
aws cloudformation describe-stacks \
  --stack-name spacex-infra \
  --region us-east-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

---

## Eliminar y redesplegar desde cero

Si necesitas limpiar todo y volver a desplegar, sigue este orden exacto:

### Paso 1: Borrar el secreto forzando eliminación inmediata

```bash
aws secretsmanager delete-secret \
  --secret-id spacex-backend-secrets \
  --force-delete-without-recovery \
  --region us-east-2
```

> **¿Por qué?** Secrets Manager marca los secretos para borrar en 7 días por defecto. Si no fuerzas el borrado inmediato, CloudFormation no podrá crear un secreto con el mismo nombre.

### Paso 2: Eliminar el stack

```bash
# 1. Borrar secreto inmediatamente
aws secretsmanager delete-secret \
  --secret-id spacex-backend-secrets \
  --force-delete-without-recovery \
  --region us-east-2

# 2. Borrar tabla DynamoDB manualmente (porque Retain la protege)
aws dynamodb delete-table \
  --table-name spaces_launches_spacex-infra \
  --region us-east-2

# 3. Esperar que la tabla se elimine
aws dynamodb wait table-not-exists \
  --table-name spaces_launches_spacex-infra \
  --region us-east-2

# 4. Eliminar el stack
aws cloudformation delete-stack \
  --stack-name spacex-infra \
  --region us-east-2

# 5. Esperar que el stack se elimine
aws cloudformation wait stack-delete-complete \
  --stack-name spacex-infra \
  --region us-east-2
```



### Paso 3: Recrear el secreto manualmente

```bash
aws secretsmanager create-secret \
  --name spacex-backend-secrets \
  --secret-string '{"TABLE_NAME":"spaces_launches_spacex-infra","PORT":"4000"}' \
  --region us-east-2
```

### Paso 4: Redesplegar la infraestructura

```bash
aws cloudformation deploy \
  --template-file infrastructure.yml \
  --stack-name spacex-infra \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Environment=prod \
  --region us-east-2
```

### Paso 6: Registrar y desplegar el task-definition del backend

```bash
# Desde la carpeta backend/
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region us-east-2 \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text
```

```bash
aws ecs update-service \
  --cluster spacex-cluster \
  --service spacex-backend-service \
  --task-definition spacex-backend-task \
  --force-new-deployment \
  --region us-east-2
```

### Paso 7: Redesplegar el código de la Lambda

Corre el workflow de GitHub Actions para la Lambda, o manualmente:

```bash
aws lambda invoke \
  --function-name spacex-launches-handler \
  --region us-east-2 \
  --payload '{}' \
  response.json && cat response.json
```

---

## Despliegue de la función Lambda

El código real de la Lambda se despliega automáticamente via **GitHub Actions** al hacer push a `main`.

---

### 

**En caso de que tu backend después de desplegar no corra por permisos esto es lo que debes hacer en la carpeta donde esté tu backend y el task-definition.json** 

# 1. Obtener el sufijo actual del secreto
SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id spacex-backend-secrets \
  --region us-east-2 \
  --query 'ARN' \
  --output text)

# 2. Actualizar task-definition con el nuevo ARN
sed -i "s|spacex-backend-secrets-[A-Za-z0-9]*|${SECRET_ARN##*:secret:}|g" task-definition.json

# 3. Agregar permisos DynamoDB al rol
aws iam put-role-policy \
  --role-name ecsTaskExecutionRole-spacex-infra \
  --policy-name DynamoDBFullAccess \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["dynamodb:Scan","dynamodb:Query","dynamodb:GetItem","dynamodb:DescribeTable"],"Resource":["arn:aws:dynamodb:us-east-2:148761674962:table/spaces_launches_spacex-infra","arn:aws:dynamodb:us-east-2:148761674962:table/spaces_launches_spacex-infra/index/*"]}]}'

# 4. Registrar y desplegar
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region us-east-2 \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text

aws ecs update-service \
  --cluster spacex-cluster \
  --service spacex-backend-service \
  --task-definition spacex-backend-task \
  --force-new-deployment \
  --region us-east-2

### Configurar secretos en GitHub

Ve a **Settings → Secrets and variables → Actions** y agrega:

| Secret | Valor |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | Access Key del usuario IAM |
| `AWS_SECRET_ACCESS_KEY` | Secret Key del usuario IAM |
| `AWS_REGION` | `us-east-2` |

### Invocar la Lambda manualmente (para pruebas)

```bash
aws lambda invoke \
  --function-name spacex-launches-handler \
  --region us-east-2 \
  --payload '{}' \
  response.json && cat response.json
```

La respuesta incluye un resumen del procesamiento:

```json
{
  "total_from_api": 205,
  "inserted_or_updated": 205,
  "skipped": 0,
  "processed_ids": ["..."]
}
```

También puedes invocarla desde la Function URL pública:

```
GET https://x2j244r7gcqo4bljyuqnwifayi0ruvxm.lambda-url.us-east-2.on.aws/
```

### Ejecución automática

La Lambda se ejecuta automáticamente cada 6 horas via EventBridge para mantener DynamoDB actualizado con los últimos lanzamientos de SpaceX.

---

## Despliegue del backend en ECS Fargate

### Infraestructura ECS (configurada manualmente una vez)

Los siguientes recursos deben existir antes del primer deploy:

- **ECS Cluster**: `spacex-cluster`
- **ECR Repository**: `spacex-backend`
- **Application Load Balancer**: `spacex-backend-alb`
- **Target Group**: `spacex-backend-tg` (puerto 4000, health check en `/health`)
- **ECS Service**: `spacex-backend-service`
- **Task Definition**: `spacex-backend-task`

### Configuración del Task Definition

El archivo `task-definition.json` en `backend/` referencia el secreto por su ARN fijo:

```json
"secrets": [
  {
    "name": "TABLE_NAME",
    "valueFrom": "arn:aws:secretsmanager:us-east-2:148761674962:secret:spacex-backend-secrets-E4UVIt:TABLE_NAME::"
  },
  {
    "name": "PORT",
    "valueFrom": "arn:aws:secretsmanager:us-east-2:148761674962:secret:spacex-backend-secrets-E4UVIt:PORT::"
  }
]
```

> ⚠️ El sufijo `E4UVIt` es fijo — es el ARN del secreto que fue creado manualmente y nunca se recrea. No cambies este valor.

### Configuración del Target Group (health check)

| Campo | Valor |
|-------|-------|
| Protocolo | HTTP |
| Puerto | 4000 |
| Ruta | `/health` |
| Códigos de éxito | `200` |

### Pipeline CI/CD automático

El workflow de GitHub Actions se activa con cada push a `main` y ejecuta:

1. Instala dependencias y corre tests
2. Construye la imagen Docker
3. Publica la imagen en ECR
4. Actualiza el Task Definition con la nueva imagen
5. Despliega en ECS Fargate y espera estabilización

### Despliegue manual del backend

```bash
# Desde la carpeta backend/

# 1. Registrar nueva revisión del task-definition
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region us-east-2 \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text

# 2. Forzar redeploy del servicio
aws ecs update-service \
  --cluster spacex-cluster \
  --service spacex-backend-service \
  --task-definition spacex-backend-task \
  --force-new-deployment \
  --region us-east-2

# 3. Verificar que tomó la revisión nueva
aws ecs describe-services \
  --cluster spacex-cluster \
  --services spacex-backend-service \
  --region us-east-2 \
  --query 'services[0].taskDefinition' \
  --output text
```

---

## Verificación del sistema

### Verificar el backend

```bash
# Health check
curl http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com/health

# Listar lanzamientos
curl http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com/launches

# Resumen estadístico
curl http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com/stats/summary

# Estadísticas por año
curl http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com/stats/by-year
```

### Verificar DynamoDB

```bash
aws dynamodb scan \
  --table-name spaces_launches_spacex-infra \
  --select COUNT \
  --region us-east-2
```

### Verificar Lambda

```bash
aws lambda get-function \
  --function-name spacex-launches-handler \
  --region us-east-2 \
  --query 'Configuration.[FunctionName,Runtime,LastModified,State]'
```

### Verificar secreto activo

```bash
aws secretsmanager get-secret-value \
  --secret-id spacex-backend-secrets \
  --region us-east-2 \
  --query 'SecretString' \
  --output text
```

---

## Arquitectura de componentes

```
GitHub Actions (CI/CD)
        │
        ├── Deploy Lambda ──────────► AWS Lambda (Python 3.11)
        │                                    │
        │                                    ▼
        │                            SpaceX API (cada 6h)
        │                                    │
        │                                    ▼
        │                           Amazon DynamoDB
        │                      spaces_launches_spacex-infra
        │
        └── Deploy Backend ─────────► Amazon ECR
                                      (imagen Docker)
                                            │
                                            ▼
                                 Application Load Balancer
                                   spacex-backend-alb
                                            │
                                            ▼
                                      ECS Fargate
                                 spacex-backend-service
                               (Node.js / Express / Puerto 4000)
                                            │
                                            ▼
                                     Amazon DynamoDB
                                     (lectura de datos)
```

---

## Recursos de infraestructura

| Recurso | Nombre |
|---------|--------|
| CloudFormation Stack | `spacex-infra` |
| DynamoDB Table | `spaces_launches_spacex-infra` |
| Lambda Function | `spacex-launches-handler` |
| EventBridge Rule | `spacex-launches-every-6h` |
| IAM Role Lambda | `spacex-lambda-execution-role-spacex-infra` |
| IAM Role ECS | `ecsTaskExecutionRole-spacex-infra` |
| Secrets Manager | `spacex-backend-secrets` (ARN sufijo: `E4UVIt`) |
| ECS Cluster | `spacex-cluster` |
| ECS Service | `spacex-backend-service` |
| ECR Repository | `spacex-backend` |
| Load Balancer | `spacex-backend-alb` |

---

## URLs públicas

| Servicio | URL |
|----------|-----|
| **Backend API** | `http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com` |
| **Swagger UI** | `http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com/api-docs` |
| **Health Check** | `http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com/health` |
| **Lambda URL** | `https://x2j244r7gcqo4bljyuqnwifayi0ruvxm.lambda-url.us-east-2.on.aws/` |

### Endpoints disponibles

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/health` | Estado del servicio |
| GET | `/launches` | Lista todos los lanzamientos |
| GET | `/launches/:id` | Detalle de un lanzamiento |
| GET | `/stats/summary` | Resumen estadístico |
| GET | `/stats/by-year` | Estadísticas por año |
| GET | `/api-docs` | Swagger UI interactivo |