import "fake-indexeddb/auto";
import { IdbStore } from "./idbStore";
import { describeStoreContract } from "./storeContract";

let counter = 0;

describeStoreContract("IdbStore", async () => new IdbStore(`test-${counter++}`));
