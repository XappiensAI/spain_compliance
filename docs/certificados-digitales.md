# Certificados digitales

DocType **Certificado Digital** (módulo Contabilidad) para guardar los certificados
PKCS#12 (`.p12` / `.pfx`) de cada compañía que usan SII, Veri*factu y la firma de
documentos.

## Qué guarda

| Campo | Notas |
|-------|-------|
| Compañía | Una compañía puede tener varios (renovaciones, uno por uso) |
| Fichero `.p12` / `.pfx` | Adjunto **privado**. Si se sube como público, no deja guardar |
| Contraseña | Campo `Password`. Frappe la cifra con el `encryption_key` del sitio y la guarda en `__Auth`, nunca en la tabla del DocType |
| Usos | SII, Veri*factu, firma. Por defecto los tres |
| Predeterminado | Uno por compañía. Si hay varios vigentes para un uso, gana este |
| Datos del certificado | Titular, NIF del titular, entidad, NIF de la entidad, emisor, número de serie, validez y huella SHA-256. Se leen del propio fichero al guardar, no se escriben a mano |
| Estado | Vigente, Próximo a caducar (60 días o menos) o Caducado |

Al guardar se abre el certificado con la contraseña. Si no abre o no trae clave
privada, da error. Si el NIF no coincide con el `tax_id` de la compañía, avisa sin
bloquear. El mismo certificado (misma huella) no se puede dar de alta dos veces en
la misma compañía.

## Seguridad

- Solo **System Manager** y **Accounts Manager** pueden ver el DocType. El fichero
  privado hereda ese permiso, así que `/private/files/...` devuelve 403 a cualquier
  otro usuario y a visitantes sin sesión.
- La contraseña nunca viaja al navegador. El formulario muestra asteriscos.
- No hay ningún método `@frappe.whitelist` que devuelva el certificado o la clave.
  Solo se usan desde código de servidor.
- Los backups con ficheros incluyen el `.p12`, que sigue cifrado con su contraseña.
  La contraseña va en la base de datos cifrada con el `encryption_key`, que está en
  `site_config.json`. Hay que custodiar los backups y el `site_config.json` por
  separado.

## Uso desde integraciones

```python
from spain_compliance.contabilidad.certificados import archivos_pem, get_certificado

# Rutas PEM temporales (0600) que se borran al salir del bloque
with archivos_pem(company, "sii") as (cert, key):
	requests.post(url, data=xml, cert=(cert, key), timeout=60)

# En memoria, para firmar (XAdES, PDF…)
c = get_certificado(company, "firma")
c.clave, c.certificado, c.cadena, c.cert_pem, c.key_pem
```

`uso` es `"sii"`, `"verifactu"` o `"firma"` (o `None` para cualquiera). Se elige el
certificado no caducado de la compañía con ese uso, primero el predeterminado y
después el que caduca más tarde. Si no hay ninguno, lanza `ValidationError`.

## Avisos de caducidad

La tarea diaria `revisar_caducidad` recalcula el estado y crea una notificación
(campana y correo, según las preferencias de cada usuario) para los System Manager
y Accounts Manager cuando faltan 60, 30, 15, 7 y 1 días, y el día que caduca.

## Renovar un certificado

1. Crear un **Certificado Digital** nuevo con el fichero renovado y marcarlo como
   predeterminado.
2. Desde ese momento las integraciones usan el nuevo, porque caduca más tarde y es
   el predeterminado.
3. El antiguo puede quedarse como histórico o borrarse. Al borrarlo se borra también
   su adjunto.
