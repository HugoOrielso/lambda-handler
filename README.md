# 🚀 SpaceX Launches — Lambda Function

Función AWS Lambda escrita en Python que consume la [API pública de SpaceX](https://api.spacexdata.com/v4/launches), transforma los datos y los almacena en Amazon DynamoDB mediante una lógica de **upsert**. Se ejecuta automáticamente cada 6 horas mediante un trigger de Amazon EventBridge y expone una URL pública para invocación manual.

---

## 📐 Arquitectura

```
EventBridge (cada 6h)
        │
        ▼
 Lambda Function  ──────►  SpaceX API (v4/launches)
        │
        ▼
   DynamoDB (spaces_launches)
        ▲
        │
Function URL (invocación manual)
https://x2j244r7gcqo4bljyuqnwifayi0ruvxm.lambda-url.us-east-2.on.aws/
```

---

## 📁 Estructura del repositorio

```
lambda/
├── lambda_function.py          # Código principal de la Lambda
├── requirements.txt            # Dependencias Python
├── infrastructure.yml          # Infraestructura como código (CloudFormation)
├── test/
│   └── test_lambda_function.py # Pruebas unitarias
└── .github/
    └── workflows/
        └── deploy-lambda.yml   # Pipeline CI/CD
```

---

## ⚙️ ¿Qué hace la Lambda?

1. **Consume** el endpoint `GET /v4/launches` de la API de SpaceX
2. **Transforma** cada lanzamiento al formato de DynamoDB:
   - `launch_id` (partition key)
   - `mission_name`, `rocket_id`, `date_utc`, `status`, `details`, entre otros
3. **Deriva el estado** de cada lanzamiento:
   - `upcoming` → próximo lanzamiento
   - `success` → lanzamiento exitoso
   - `failed` → lanzamiento fallido
   - `unknown` → estado indeterminado
4. **Inserta o actualiza** los registros en DynamoDB usando `batch_writer` (upsert)
5. **Retorna un resumen** con totales procesados, insertados y omitidos

---

### Invocar la Lambda manualmente
```bash
curl https://ijkudn6zzsaz5dvkrraiyy3gcu0jpows.lambda-url.us-east-2.on.aws/
```

> ⚠️ **Si devuelve error de permisos**, ejecuta:
> ```bash
> aws lambda add-permission \
>   --function-name spacex-launches-handler \
>   --statement-id AllowPublicAccess \
>   --action lambda:InvokeFunctionUrl \
>   --principal "*" \
>   --function-url-auth-type NONE \
>   --region us-east-2
> ```
> O ve a **Lambda → Configuración → URL de la función → Editar** y cambia el tipo de autorización a `NONE`.

---

```
GET https://ijkudn6zzsaz5dvkrraiyy3gcu0jpows.lambda-url.us-east-2.on.aws/
```

### Respuesta esperada:
```json
{
  "total_from_api": 205,
  "inserted_or_updated": 205,
  "skipped": 0,
  "processed_ids": ["abc123", "def456", "..."],
  "skipped_ids": []
}
```

---

## 🛠️ Despliegue de infraestructura desde cero

La infraestructura está definida en `infrastructure.yml` (CloudFormation) e incluye:

| Recurso | Nombre |
|---------|--------|
| DynamoDB Table | `spaces_launches` |
| IAM Role Lambda | `spacex-lambda-execution-role` |
| Lambda Function | `spacex-launches-handler` |
| Lambda Function URL | pública, sin auth |
| EventBridge Rule | cada 6 horas |
| IAM Role ECS | `ecsTaskExecutionRole` |
| Secrets Manager | `spacex-backend-secrets` |

### Prerrequisitos
- AWS CLI configurado (`aws configure`)
- Permisos de IAM para CloudFormation, Lambda, DynamoDB, EventBridge

### Desplegar infraestructura
```bash
aws cloudformation deploy \
  --template-file infrastructure.yml \
  --stack-name spacex-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-2
```

### Verificar el stack
```bash
aws cloudformation describe-stacks \
  --stack-name spacex-stack \
  --region us-east-2 \
  --query 'Stacks[0].StackStatus'
```

> ⚠️ Si los recursos ya existen en tu cuenta, CloudFormation los detecta y solo aplica los cambios necesarios.

---

## 🔁 Pipeline CI/CD (GitHub Actions)

El workflow `.github/workflows/deploy-lambda.yml` se activa automáticamente con cada push a `main` que modifique archivos relevantes.

### Triggers
```yaml
on:
  push:
    branches: [main]
    paths:
      - "lambda_function.py"
      - "requirements.txt"
      - "test/**"
      - ".github/workflows/deploy-lambda.yml"
  workflow_dispatch:   # También permite ejecución manual desde GitHub
```

### Flujo del pipeline

```
Push a main
    │
    ▼
┌─────────────────────────────┐
│  JOB: test                  │
│  1. Checkout código         │
│  2. Setup Python 3.11       │
│  3. Instalar dependencias   │
│  4. Ejecutar pytest         │
│     └─ cobertura mínima 80% │
└────────────┬────────────────┘
             │ (solo si tests pasan)
             ▼
┌─────────────────────────────┐
│  JOB: deploy                │
│  1. Checkout código         │
│  2. Configurar AWS CLI      │
│  3. Build package (.zip)    │
│  4. Deploy a Lambda         │
│  5. Esperar actualización   │
│  6. Verificar despliegue    │
└─────────────────────────────┘
```

### Secrets requeridos en GitHub

Ve a **Settings → Secrets and variables → Actions** y agrega:

| Secret | Descripción |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | Access key de IAM |
| `AWS_SECRET_ACCESS_KEY` | Secret key de IAM |

---

## 🧪 Correr pruebas localmente

### Instalar dependencias
```bash
pip install -r requirements.txt pytest pytest-cov
```

### Ejecutar pruebas
```bash
pytest test/test_lambda_function.py -v \
  --cov=lambda_function \
  --cov-report=term-missing \
  --cov-fail-under=80
```

### Cobertura esperada
El pipeline requiere **mínimo 80% de cobertura**. Las pruebas cubren:

- `map_status` → derivación de estados (upcoming, success, failed, unknown)
- `transform_launch` → transformación y validación de campos
- `upsert_launches` → escritura en DynamoDB con batch_writer
- `process_launches` → orquestación completa
- `fetch_launches` → manejo de errores HTTP
- `lambda_handler` → respuestas HTTP vs EventBridge

---

## 🗄️ Tabla DynamoDB

**Nombre:** `spaces_launches`  
**Región:** `us-east-2`  
**Modo:** On-demand (Pay per request)  
**Partition key:** `launch_id` (String)

### Campos almacenados

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `launch_id` | String | ID único del lanzamiento (PK) |
| `mission_name` | String | Nombre de la misión |
| `flight_number` | Number | Número de vuelo |
| `date_utc` | String | Fecha UTC del lanzamiento |
| `status` | String | upcoming / success / failed / unknown |
| `rocket_id` | String | ID del cohete |
| `launchpad_id` | String | ID de la plataforma |
| `details` | String | Descripción del lanzamiento |
| `article` | String | Link al artículo |
| `webcast` | String | Link al webcast |
| `patch_small` | String | URL del parche de la misión |

---

## 🔗 Recursos relacionados

- [API SpaceX v4](https://api.spacexdata.com/v4/launches)
- [AWS Lambda Docs](https://docs.aws.amazon.com/lambda/)
- [Amazon DynamoDB Docs](https://docs.aws.amazon.com/dynamodb/)