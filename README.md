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
   DynamoDB (spaces_launches_spacex-infra)
        ▲
        │
Function URL (invocación manual)
https://ijkudn6zzsaz5dvkrraiyy3gcu0jpows.lambda-url.us-east-2.on.aws/
```

---

## 📁 Estructura del repositorio

```
lambda-handler/
├── lambda_function.py          # Código principal de la Lambda
├── requirements.txt            # Dependencias Python
├── requirements-dev.txt        # Dependencias de desarrollo/testing
├── conftest.py                 # Configuración de pytest
├── infrastructure.yml          # Infraestructura como código (CloudFormation)
├── cloudformation.md           # Guía completa de despliegue
├── test/
│   └── test_lambda_function.py # Pruebas unitarias (17 tests, 97.75% cobertura)
└── .github/
    └── workflows/
        └── deploy-lambda.yml   # Pipeline CI/CD con rollback automático
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

## 🌐 Invocar la Lambda manualmente

```bash
curl https://ijkudn6zzsaz5dvkrraiyy3gcu0jpows.lambda-url.us-east-2.on.aws/
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

## 🛠️ Despliegue de infraestructura desde cero

La infraestructura está definida en `infrastructure.yml` (CloudFormation) e incluye:

| Recurso | Nombre |
|---------|--------|
| DynamoDB Table | `spaces_launches_spacex-infra` |
| IAM Role Lambda | `spacex-lambda-execution-role-spacex-infra` |
| Lambda Function | `spacex-launches-handler` |
| Lambda Function URL | pública, sin auth |
| EventBridge Rule | `spacex-launches-every-6h` (cada 6 horas) |
| IAM Role ECS | `ecsTaskExecutionRole-spacex-infra` |

> 📖 Para el proceso completo de despliegue y redespliegue desde cero ver [`cloudformation.md`](./cloudformation.md)

### Prerrequisitos
- AWS CLI configurado (`aws configure`)
- Permisos de IAM para CloudFormation, Lambda, DynamoDB, EventBridge

### Desplegar infraestructura
```bash
aws cloudformation deploy \
  --template-file infrastructure.yml \
  --stack-name spacex-infra \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Environment=prod \
  --region us-east-2
```

### Verificar el stack
```bash
aws cloudformation describe-stacks \
  --stack-name spacex-infra \
  --region us-east-2 \
  --query 'Stacks[0].StackStatus'
```

---

## 🔁 Pipeline CI/CD con rollback automático

El workflow `.github/workflows/deploy-lambda.yml` se activa con cada push a `main`.

### Flujo del pipeline

```
Push a main
    │
    ▼
┌─────────────────────────────────┐
│  JOB: test                      │
│  1. Checkout código             │
│  2. Setup Python 3.11           │
│  3. Instalar dependencias       │
│  4. Ejecutar pytest             │
│     └─ cobertura mínima 80%     │
└──────────────┬──────────────────┘
               │ (solo si tests pasan)
               ▼
┌─────────────────────────────────┐
│  JOB: deploy                    │
│  1. Guardar versión actual      │  ← snapshot para rollback
│     como punto de restauración  │
│  2. Build package (.zip)        │
│  3. Deploy a Lambda             │
│  4. Esperar actualización       │
│  5. Smoke test (invoke + 200)   │
│     ├─ ✅ OK → deploy exitoso   │
│     └─ ❌ Falla → rollback      │  ← vuelve a versión anterior
│  6. Verificar despliegue        │
└─────────────────────────────────┘
```

### ¿Cómo funciona el rollback?

Antes de cada deploy el pipeline publica una **versión numerada** de la Lambda actual como snapshot. Después del deploy se corre un smoke test que invoca la Lambda y verifica que responde `200`. Si falla, el pipeline restaura automáticamente la versión anterior sin intervención manual.

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
python -m pip install -r requirements-dev.txt
```

### Ejecutar pruebas
```bash
python -m pytest test/test_lambda_function.py -v \
  --cov=lambda_function \
  --cov-report=term-missing \
  --cov-fail-under=80
```

### Resultado esperado
```
17 passed in 1.52s
Coverage: 97.75% ✅
```

### Cobertura por módulo

| Función | Descripción |
|---------|-------------|
| `map_status` | Derivación de estados (upcoming, success, failed, unknown) |
| `transform_launch` | Transformación y validación de campos |
| `upsert_launches` | Escritura en DynamoDB con batch_writer |
| `process_launches` | Orquestación completa del flujo |
| `fetch_launches` | Manejo de errores HTTP de la API |
| `lambda_handler` | Respuestas HTTP vs EventBridge |

---

## 🗄️ Tabla DynamoDB

**Nombre:** `spaces_launches_spacex-infra`
**Región:** `us-east-2`
**Modo:** On-demand (Pay per request)
**Partition key:** `launch_id` (String)
**GSI:** `date_utc-index` — permite consultas por fecha

### Campos almacenados

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `launch_id` | String | ID único del lanzamiento (PK) |
| `mission_name` | String | Nombre de la misión |
| `flight_number` | Number | Número de vuelo |
| `date_utc` | String (GSI) | Fecha UTC del lanzamiento |
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