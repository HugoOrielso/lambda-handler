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

El archivo `infrastructure.yml` en la raíz del repositorio crea todos los recursos base:

- Tabla **DynamoDB** (`spaces_launches_spacex-infra`)
- **Lambda** placeholder (`spacex-launches-handler`)
- **EventBridge Rule** (ejecución cada 6 horas)
- **IAM Roles** para Lambda y ECS
- **Secrets Manager** con variables de entorno del backend

### Paso 1: Validar el template

```bash
aws cloudformation validate-template \
  --template-body file://infrastructure.yml \
  --region us-east-2
```

### Paso 2: Desplegar el stack

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

### Paso 3: Verificar los outputs

```bash
aws cloudformation describe-stacks \
  --stack-name spacex-infra \
  --region us-east-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

Esto muestra el nombre de la tabla DynamoDB, ARN de la Lambda, URL de la función y ARN del rol ECS.

### ⚠️ Notas importantes

- Si ya existen recursos con los mismos nombres (Lambda, EventBridge rule), elimínalos antes de desplegar:

```bash
# Eliminar Lambda existente
aws lambda delete-function \
  --function-name spacex-launches-handler \
  --region us-east-2

# Eliminar regla de EventBridge
aws events delete-rule \
  --name spacex-launches-every-6h \
  --region us-east-2
```

- Si el stack queda en estado `ROLLBACK_COMPLETE`, elimínalo y vuelve a desplegarlo:

```bash
aws cloudformation delete-stack \
  --stack-name spacex-infra \
  --region us-east-2
```

---

## Eliminar y redesplegar desde cero

Si necesitas limpiar todo y volver a desplegar (por ejemplo, para probar el flujo completo):

### Paso 1: Eliminar el stack de CloudFormation

```bash
aws cloudformation delete-stack \
  --stack-name spacex-infra \
  --region us-east-2
```

### Paso 2: Esperar a que se elimine completamente

```bash
aws cloudformation describe-stacks \
  --stack-name spacex-infra \
  --region us-east-2
```

Cuando veas el error `Stack with id spacex-infra does not exist` significa que todos los recursos fueron eliminados correctamente (DynamoDB, Lambda, EventBridge, IAM roles, Secrets Manager).

### Paso 3: Redesplegar la infraestructura

```bash
aws cloudformation deploy \
  --template-file infrastructure.yml \
  --stack-name spacex-infra \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Environment=prod \
  --region us-east-2
```

### Paso 4: Redesplegar el código de la Lambda

Corre el workflow de GitHub Actions para la Lambda, o manualmente:

```bash
aws lambda invoke \
  --function-name spacex-launches-handler \
  --region us-east-2 \
  --payload '{}' \
  response.json && cat response.json
```

### Paso 5: Redesplegar el backend en ECS

Corre el workflow de GitHub Actions para el backend (push a `main` o trigger manual desde Actions).

> ⚠️ **Importante:** Al eliminar el stack, el secret `spacex-backend-secrets` también se elimina. CloudFormation lo recrea automáticamente con el `TABLE_NAME` correcto al redesplegar.

---

## Despliegue de la función Lambda

El código real de la Lambda se despliega automáticamente via **GitHub Actions** al hacer push a `main`.

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

### Configuración del Target Group (health check)

Asegúrate de que el health check del Target Group esté configurado así:

| Campo | Valor |
|-------|-------|
| Protocolo | HTTP |
| Puerto | 4000 |
| Ruta | `/health` |
| Códigos de éxito | `200` |

### Variables de entorno del backend

Las variables se obtienen de **Secrets Manager** (`spacex-backend-secrets`):

```json
{
  "TABLE_NAME": "spaces_launches_spacex-infra",
  "PORT": "4000"
}
```

### Pipeline CI/CD automático

El workflow de GitHub Actions se activa con cada push a `main` y ejecuta:

1. Instala dependencias y corre tests
2. Construye la imagen Docker
3. Publica la imagen en ECR
4. Actualiza el Task Definition con la nueva imagen
5. Despliega en ECS Fargate y espera estabilización

### Despliegue manual (si se necesita)

```bash
# Build y push de imagen
aws ecr get-login-password --region us-east-2 | \
  docker login --username AWS --password-stdin \
  <account-id>.dkr.ecr.us-east-2.amazonaws.com

docker build -t spacex-backend .
docker tag spacex-backend:latest \
  <account-id>.dkr.ecr.us-east-2.amazonaws.com/spacex-backend:latest
docker push \
  <account-id>.dkr.ecr.us-east-2.amazonaws.com/spacex-backend:latest
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
        └── Deploy ECS ───────────► Amazon DynamoDB
                │                   spaces_launches_spacex-infra
                ▼
         Amazon ECR
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

## URLs públicas

| Servicio | URL |
|----------|-----|
| **Backend API** | `http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com` |
| **Swagger UI** | `http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com/api-docs` |
| **Health Check** | `http://spacex-backend-alb-574561858.us-east-2.elb.amazonaws.com/health` |

### Endpoints disponibles

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/health` | Estado del servicio |
| GET | `/launches` | Lista todos los lanzamientos |
| GET | `/launches/:id` | Detalle de un lanzamiento |
| GET | `/stats/summary` | Resumen estadístico |
| GET | `/stats/by-year` | Estadísticas por año |