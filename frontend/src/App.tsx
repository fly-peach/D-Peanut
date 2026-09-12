import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation'
import { Message, MessageContent } from '@/components/ai-elements/message'
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from '@/components/ai-elements/prompt-input'
import { Task, TaskContent, TaskItem, TaskTrigger } from '@/components/ai-elements/task'
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from '@/components/ai-elements/tool'
import { Streamdown } from 'streamdown'

const planSteps = [
  '读取 sales.csv 画像（行数 / 列类型 / 缺失率）',
  '按城市聚合销售额（DuckDB）',
  '生成 Top5 柱状图 ChartSpec',
]

const sampleCode = `import duckdb

top5 = duckdb.sql("""
  SELECT city, SUM(amount) AS total
  FROM sales
  GROUP BY city
  ORDER BY total DESC
  LIMIT 5
""").df()
print(top5)`

const finalAnswerMd = `**Top 5 城市销售额**（静态演示数据）：

| 城市 | 销售额 |
| --- | --- |
| 上海 | ¥1,284,500 |
| 北京 | ¥1,102,300 |
| 深圳 | ¥986,700 |
| 广州 | ¥874,200 |
| 杭州 | ¥812,900 |

> M0 阶段为静态渲染样例；M3 接入 useChat 后由 Run 流实时驱动。`

function App() {
  return (
    <main className="mx-auto flex h-dvh max-w-3xl flex-col px-4">
      <header className="py-4">
        <h1 className="text-lg font-semibold">data-agent · M0 静态渲染样例</h1>
        <p className="text-muted-foreground text-sm">
          ai-elements 组件演示：Conversation / Task / Tool / PromptInput（M3 接入 useChat 实时流）
        </p>
      </header>

      <Conversation className="flex-1">
        <ConversationContent>
          <Message from="user">
            <MessageContent>销售额 top5 的城市是哪些？画一张柱状图</MessageContent>
          </Message>

          <Message from="assistant">
            <MessageContent>
              <Task defaultOpen>
                <TaskTrigger title="分析计划：Top5 城市销售额" />
                <TaskContent>
                  {planSteps.map((s) => (
                    <TaskItem key={s}>{s}</TaskItem>
                  ))}
                </TaskContent>
              </Task>
            </MessageContent>
          </Message>

          <Message from="assistant">
            <MessageContent>
              <Tool defaultOpen>
                <ToolHeader type="tool-execute_code" state="output-available" />
                <ToolContent>
                  <ToolInput input={{ purpose: '按城市聚合销售额', code: sampleCode }} />
                  <ToolOutput output="✅ 返回 5 行 · 12ms" errorText={undefined} />
                </ToolContent>
              </Tool>
            </MessageContent>
          </Message>

          <Message from="assistant">
            <MessageContent>
              <Streamdown>{finalAnswerMd}</Streamdown>
            </MessageContent>
          </Message>
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="py-4">
        <PromptInput onSubmit={() => {}}>
          <PromptInputBody>
            <PromptInputTextarea placeholder="M0 静态样例：M3 将接入 useChat 实时流" />
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputTools />
            <PromptInputSubmit status="ready" />
          </PromptInputFooter>
        </PromptInput>
      </div>
    </main>
  )
}

export default App
