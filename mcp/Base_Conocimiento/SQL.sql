DROP TABLE IF EXISTS historial_chat;
DROP TABLE IF EXISTS menus_diarios;
DROP TABLE IF EXISTS platos_nuevos;
DROP TABLE IF EXISTS cache_semaforo;

-- Tabla 1: Memoria de conversación entre sesiones
CREATE  TABLE historial_chat (
    id       INT IDENTITY(1,1) PRIMARY KEY,
    fecha    DATETIME2 DEFAULT GETDATE(),
	thread_id VARCHAR(100) DEFAULT 'encargado-1',
    rol      VARCHAR(20) NOT NULL,
    contenido NVARCHAR(MAX) NOT NULL
);

-- Tabla 2: Menú diario con semáforo por dimensión
CREATE  TABLE menus_diarios (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    fecha         DATE NOT NULL,
    turno         VARCHAR(20) NOT NULL,
    plato_nombre  NVARCHAR(200) NOT NULL,
    energia       CHAR(1),
    carbohidratos CHAR(1),
    proteina      CHAR(1),
    grasas        CHAR(1),
    fibra         CHAR(1),
    sodio         CHAR(1),
    fecha_registro DATETIME2 DEFAULT GETDATE()
);

-- Tabla 3: Platos nuevos registrados por el encargado
CREATE  TABLE platos_nuevos (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    nombre         NVARCHAR(200) NOT NULL,
    insumo         NVARCHAR(100),
    rol            NVARCHAR(50),
    turno          NVARCHAR(50),
    guarniciones   NVARCHAR(500),
    fecha_registro DATETIME2 DEFAULT GETDATE()
);

CREATE TABLE cache_semaforo (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    nombre         NVARCHAR(200) NOT NULL UNIQUE,
    energia        CHAR(1),
    carbohidratos  CHAR(1),
    proteina       CHAR(1),
    grasas         CHAR(1),
    fibra          CHAR(1),
    sodio          CHAR(1),
    fecha_registro DATETIME2 DEFAULT GETDATE()
);

select*from platos_nuevos;
select*from menus_diarios where fecha='2026-10-04';
select*from cache_semaforo;
select*from historial_chat;

truncate table platos_nuevos;
truncate table menus_diarios;
truncate table cache_semaforo;
truncate table historial_chat;