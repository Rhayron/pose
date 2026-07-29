# Prompt para Survey Bibliográfico — Estimação Visual de Pose 6DoF de Transdutor Ultrassônico para Inspeção Subaquática por END

Copie o bloco abaixo e envie para um modelo com acesso a busca na web (idealmente com ferramentas de busca acadêmica real, tipo Google Scholar, Semantic Scholar, arXiv, IEEE Xplore).

---

## PROMPT

Você é um assistente de pesquisa acadêmica especializado em visão computacional, robótica subaquática e ensaios não destrutivos (END) por ultrassom. Sua tarefa é conduzir um **survey bibliográfico aprofundado e atualizado** para fundamentar uma dissertação de mestrado. Leia todo o escopo abaixo antes de começar.

### Regras inegociáveis (evitar alucinação)

1. **NUNCA invente, parafraseie de memória ou "reconstrua" uma referência.** Toda fonte citada deve ter sido efetivamente localizada por você via busca real (motor de busca, base acadêmica, ou navegação de página).
2. Para cada fonte, forneça: título exato, autores, ano, veículo de publicação (periódico/conferência/preprint), link ou DOI verificável, e um resumo de 2-4 linhas da contribuição relevante ao tema.
3. Se não conseguir confirmar a existência de uma fonte que "lembra" de leituras anteriores, **não a inclua** — prefira marcar como "não verificado, buscar posteriormente" a arriscar uma alucinação.
4. Priorize fontes primárias (artigos peer-reviewed, teses, relatórios técnicos de institutos como SINTEF/IEEE) sobre agregadores, blogs ou wikis.
5. Diferencie claramente no texto entre: (a) resultado consolidado e citável, (b) tendência de pesquisa ainda não consolidada, (c) lacuna identificada (gap) que a pesquisa atual pretende preencher.
6. Ao final de cada seção, inclua uma pequena tabela com: Referência | Ano | Tipo (jornal/conf/preprint) | Contribuição principal | Link/DOI.
7. Se uma busca não retornar nada relevante, diga isso explicitamente em vez de preencher a lacuna com algo genérico.

### Escopo e delimitação da pesquisa (contexto obrigatório)

**Hipótese central:** a estimação visual da pose 6DoF (6 graus de liberdade — posição + orientação) de um transdutor ultrassônico, combinada a um método de reconstrução de imagens de ultrassom, pode reduzir a dependência de encoders eletromecânicos em inspeções subaquáticas por END e melhorar o registro espacial dos sinais adquiridos.

**Pipeline proposto (2 fases):**
- **Fase 1 (foco principal da dissertação):** módulo de estimação de pose 6DoF do transdutor/braçadeira a partir de imagens subaquáticas, parâmetros de calibração de câmera, modelo CAD do conjunto, e (quando aplicável) marcadores fiduciais. Abordagem de Deep Learning combinando: (i) estratégia inspirada na **PVNet** (estimação de keypoints via campos vetoriais densos, robusta a oclusão parcial e turbidez); (ii) estratégia inspirada no **Deep ChArUco** (detecção fiducial + refinamento subpixel de pontos 2D).
- **Fase 2 (escopo restrito — NÃO inclui reconstrução de imagem):** uso da pose estimada para posicionar espacialmente (registro 3D) imagens de ultrassom já reconstruídas (A-scan/B-scan/C-scan), sem entrar no mérito do algoritmo de reconstrução em si.

**Contexto de aplicação:** inspeção subaquática de dutos/tubulações de aço por END ultrassônico, tipicamente usando varredura setorial (S-scan) com lente acústica focada, ou, na ausência de lente, algoritmos como **TFM (Total Focusing Method)** ou **CPWC (Compounding Plane Wave Compounding)**.

**Ambiente experimental:** testes em tanque de laboratório (LASSIP/UTFPR), com transdutor/braçadeira posicionado sobre amostra de tubulação.

### Estrutura obrigatória do survey

Produza o survey nas seguintes seções, cada uma com busca dedicada:

1. **Introdução e delimitação do problema**
   - Panorama de inspeção subaquática por END: motivação, desafios (visibilidade, refração, distorção óptica, ausência de GPS/odometria confiável).
   - Por que odometria/encoders eletromecânicos são limitados nesse contexto.

2. **Estimação de pose 6DoF por visão computacional — fundamentos**
   - Survey de métodos gerais de 6D pose estimation (deep learning), incluindo pontos fortes/fracos e campos de aplicação.
   - Comparação entre abordagens baseadas em keypoints densos (estilo PVNet) vs. regressão direta vs. correspondência de features.

3. **Estimação de pose e keypoints sob condições subaquáticas adversas**
   - Trabalhos específicos de 6DoF pose estimation em ambiente subaquático (ex.: SINTEF, AUV/ROV swarm sensing).
   - Robustez a turbidez, oclusão parcial, baixa luminosidade, backscatter.
   - Uso de dados sintéticos e transferência de domínio (sim-to-real) para treinar esses modelos.

4. **Detecção de marcadores fiduciais em condições difíceis**
   - Família ArUco/ChArUco e variantes robustas (Deep ChArUco, DeepArUco++, RefineNet/ChArUcoNet).
   - Marcadores fiduciais ativos para posicionamento subaquático industrial.
   - Comparações de precisão entre marcadores fiduciais e métodos sem marcador (markerless).

5. **Visão computacional subaquática — desafios ópticos e de calibração**
   - Distorção refrativa em câmeras subaquáticas e ferramentas de calibração.
   - Design óptico e polarização para imageamento subaquático.
   - Técnicas de melhoria/realce de imagem subaquática (enhancement) usadas como pré-processamento.

6. **Odometria visual e SLAM aplicados a veículos/sistemas subaquáticos**
   - Visual-inertial odometry, SLAM visual, e sua relação conceitual com o problema de rastreamento de pose do transdutor.

7. **Reconstrução de imagens de ultrassom por END (contexto, não escopo central)**
   - TFM, CPWC, varredura setorial com lente acústica: princípios, uso em inspeção de dutos/tubulações de aço, limitações que motivam a necessidade de melhor registro espacial.
   - Trabalhos que integrem informação de pose/trajetória externa ao pipeline de reconstrução ultrassônica (se existirem — é provável que seja uma lacuna).

8. **Integração pose + imagem: registro espacial 3D de dados de END**
   - Trabalhos (em qualquer domínio de END, não só ultrassom) que usem pose 6DoF de um sensor para posicionar espacialmente múltiplas aquisições 2D em uma representação 3D.
   - Esse é o núcleo da contribuição da dissertação — busque ativamente por qualquer trabalho semelhante para posicionar corretamente o ineditismo (novelty) da pesquisa.

9. **Síntese e identificação de lacunas (gap analysis)**
   - Quadro comparativo consolidando o que já existe separadamente (pose 6DoF subaquática robusta E reconstrução ultrassônica por TFM/CPWC/S-scan) versus o que ainda não existe (integração direta dos dois em um pipeline validado experimentalmente).
   - Posicionamento explícito de como a pesquisa atual se diferencia do estado da arte.

10. **Referências consolidadas**
    - Lista final única, sem duplicatas, ordenada por seção, com todos os campos exigidos na regra 2.

### Observações finais para o modelo executor

- Sempre que possível, priorize publicações dos últimos 5 anos (2021-2026), mas inclua clássicos fundamentais (ex.: paper original do PVNet, do ArUco) mesmo se mais antigos, pois são referências estruturais.
- Ao citar qualquer artigo, confirme que o link/DOI resolve para o conteúdo descrito antes de incluí-lo.
- Se o volume de literatura em alguma subseção for escasso (provável nas seções 8 e 9, que tratam do gap específico), diga isso explicitamente — essa escassez é, em si, um dado relevante para a dissertação (evidência da lacuna).
- Ao final, aponte quais das referências levantadas anteriormente pelo autor (ver lista abaixo) você conseguiu **confirmar como reais e corretamente descritas**, e quais não conseguiu verificar ou encontrou com conteúdo diferente do esperado.

### Referências previamente levantadas pelo autor (a serem VERIFICADAS, não assumidas como corretas)

- Stereo Vision System for Vision-Based Control of Inspection-Class ROVs
- Underwater 6D Pose Estimation — SINTEF
- Studies on Underwater Image Processing Using Artificial Intelligence Technologies
- Robust underwater object tracking with image enhancement and two-step feature compression
- Optical Design and Polarization Analysis for Full-Polarization Underwater Imaging Lens
- A Calibration Tool for Refractive Underwater Vision
- Active Fiducial Marker-Based Precise Underwater Positioning System for Industrial and Robotics Applications
- Experimental Evaluation of Precision Positioning in Unmanned Aerial Systems Using Fiducial Markers
- Reviewing 6D Pose Estimation: Model Strengths, Limitations, and Application Fields
- Deep ChArUco: Dark ChArUco Marker Pose Estimation
- DeepArUco++: improved detection of square fiducial markers in challenging lighting conditions
- Enhancing Inter-AUV Perception: Adaptive 6-DOF Pose Estimation with Synthetic Images for AUV Swarm Sensing
- Visual-Inertial Odometry and SLAM — Robotics and Perception Group
- Robust and Fair Undersea Target Detection with Automated Underwater Vehicles for Biodiversity Data Collection

**Importante:** essa lista foi gerada anteriormente por um LLM e já continha ao menos uma alucinação identificada pelo orientador. Trate-a como ponto de partida a ser auditado, não como verdade estabelecida.

---

*Fim do prompt.*