import { MemoryStore } from "./memoryStore";
import { describeStoreContract } from "./storeContract";

describeStoreContract("MemoryStore", async () => new MemoryStore());
