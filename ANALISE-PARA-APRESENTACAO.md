# Análise interpretável do HAR para a apresentação

## Achado central

A hipótese visual é confirmada: o contraste mais forte do HAR é entre
**atividades dinâmicas** (andar e subir/descer escadas) e **atividades
estáticas** (sentar, ficar em pé e deitar). Isso é uma diferença de padrão
inercial, não uma posição física nem uma velocidade representada pelos eixos
do embedding.

## Evidência quantitativa nas projeções

| Projeção | Silhouette estático×dinâmico | Pureza local K=10 | Separação dos centroides | Efeito no eixo atual X | Efeito no eixo atual Y |
|---|---:|---:|---:|---:|---:|
| PCA | 0,700 | 0,998 | 3,445 | 4,521 | -0,350 |
| t-SNE p=30 | 0,413 | 0,999 | 1,836 | 3,628 | 0,082 |
| UMAP equilibrado | 0,701 | 0,999 | 3,852 | -8,438 | -0,373 |

**Como ler:** pureza local é a fração média dos 15 vizinhos que pertence
ao mesmo macrogrupo. Os efeitos X/Y descrevem somente a orientação fixa
desta execução; t-SNE e UMAP podem ser girados, refletidos ou invertidos
sem alterar seu significado.

## O que realmente diferencia movimento e postura

As maiores diferenças padronizadas entre dinâmico e estático foram:

| Característica HAR | Dinâmico − estático |
|---|---:|
| `fBodyAccJerk-entropy()-X` | 1,963σ |
| `fBodyAccJerk-entropy()-Y` | 1,949σ |
| `tBodyAccJerkMag-entropy()` | 1,944σ |
| `tBodyAccJerk-entropy()-X` | 1,943σ |
| `fBodyAcc-entropy()-X` | 1,941σ |
| `fBodyBodyAccJerkMag-entropy()` | 1,937σ |
| `tBodyAccJerk-entropy()-Z` | 1,933σ |
| `tBodyAccJerk-entropy()-Y` | 1,929σ |
| `fBodyAccJerk-entropy()-Z` | 1,921σ |
| `fBodyAcc-entropy()-Y` | 1,914σ |

Valores positivos aparecem mais no grupo dinâmico; negativos aparecem
mais no grupo estático. Termos `BodyAcc`, `BodyGyro`, `Jerk`, `energy` e
bandas de frequência descrevem intensidade, variação e frequência do
movimento do smartphone.

## Como interpretar o PCA

PC1 explica **50,7%** e PC2
explica **6,2%** da variância
padronizada; juntas, **57,0%**.

Características mais relacionadas a PC1:

- `fBodyAcc-sma()`: correlação 0,989.
- `fBodyAccJerk-sma()`: correlação 0,988.
- `fBodyGyro-sma()`: correlação 0,988.
- `tBodyAccJerk-sma()`: correlação 0,988.
- `tBodyAccJerkMag-mean()`: correlação 0,987.
- `tBodyAccJerkMag-sma()`: correlação 0,987.
- `fBodyBodyAccJerkMag-sma()`: correlação 0,980.

Características mais relacionadas a PC2:

- `fBodyAcc-meanFreq()-Z`: correlação 0,736.
- `tBodyGyroMag-arCoeff()1`: correlação 0,713.
- `fBodyAccMag-meanFreq()`: correlação 0,708.
- `tGravityAcc-arCoeff()-Z,1`: correlação 0,708.
- `tBodyAccMag-arCoeff()1`: correlação 0,707.
- `tGravityAccMag-arCoeff()1`: correlação 0,707.
- `tGravityAcc-arCoeff()-Z,2`: correlação -0,706.

O PCA parece mais sobreposto porque ele procura variância linear global,
não separação de classes. Sobreposição não significa falha: ela mostra que
duas componentes lineares não capturam toda a geometria das seis atividades.

## O que dizer sobre t-SNE e UMAP

- **Seguro:** atividades estáticas e dinâmicas ocupam regiões diferentes e
  possuem alta coerência de vizinhança nesta execução.
- **Seguro:** sentado e em pé tendem a ficar próximos porque ambos têm pouca
  dinâmica corporal; subir, descer e andar compartilham movimento periódico.
- **Não dizer:** esquerda significa movimento, direita significa repouso ou
  UMAP-1/t-SNE-1 significa velocidade. A orientação pode inverter.
- **Não dizer:** a distância visual entre dois clusters é uma distância física.

## Roteiro curto para o slide

> Primeiro removemos as cores e aplicamos três objetivos diferentes ao mesmo
> vetor de 561 características. Quando revelamos os rótulos, surge uma divisão
> consistente entre atividades dinâmicas e estáticas. PCA mostra essa tendência
> de forma linear e sobreposta; t-SNE e UMAP preservam melhor as vizinhanças
> locais. A posição esquerda/direita não tem significado físico: o resultado
> relevante é quem permanece vizinho de quem.

## Uso recomendado do dataset

O HAR cumpre o papel se a pergunta for **como diferentes métodos organizam
padrões de movimento e postura captados por sensores**. Ele não é adequado para
mostrar posição de pessoas, trajetória ou velocidade espacial. Para uma segunda
demonstração imediatamente reconhecível, use dígitos como contingência visual,
sem abandonar o HAR como caso real principal.
