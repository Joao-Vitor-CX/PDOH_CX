# Homologação isolada da Central no App Shell PDOH_CX

Abra http://127.0.0.1:5174/impactadores?visao=geral&periodo=personalizado&periodo_inicio=2026-09-01&periodo_fim=2026-09-01

1. Inicial: o App Shell real e a tela real Impactadores carregam; o sino não tem badge.
2. Clique **Disponibilizar resultado homologado** e recarregue a página.
3. O header real mostra o sino com badge 1; a tela Impactadores mostra a oportunidade sintética única.
4. Clique no sino e abra a oportunidade CHECKOUT_AUSENTE de COLABORADOR TESTE 44H. Os detalhes usam a UI de produção.
5. Ao abrir, a leitura remove o badge; o item permanece na lista recente.
6. Atualizar mantém o contador zerado e o item recente; **Reiniciar contador** restaura o estado inicial vazio.

O servidor serve o `index.html` real do PDOH_CX e monta `AppShell`, `ImpactPage` e `OpportunityNotifications` reais. Menu, header, navegação, cores, espaços, cartões, diálogos e detalhes vêm do aplicativo. A entrada temporária fornece ao `AppShell` a identidade visual “Homologação visual”, só neste preview. Há uma faixa identificando o fixture e oferecendo os controles do teste. As chamadas de dados são interceptadas localmente e servem somente vazio ou as respostas isoladas capturadas da API de homologação. Não instala proxy; não chama API, banco ou processamento real. O deploy/release e a API não são iniciados nem alterados.

Iniciar em PowerShell:
`cd C:\Users\RT-138\Desktop\PDOH_CX\frontend`
`npm.cmd run dev -- --config vite.visual-notifications.config.ts`

O entrypoint altera apenas o comportamento deste servidor temporário; não altera o `index.html` nem o ponto de entrada de produção. Esta pasta, massa JSON e servidor devem ser removidos/encerrados somente após a aprovação visual expressa do usuário, conforme pedido.
